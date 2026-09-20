"""Budget circuit breaker: a cost ceiling per mission that pauses instead of burning."""
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages.utils import count_tokens_approximately

from . import ledger

# ponytail: flat Sonnet-class rates, USD per token. Pull live pricing
# from config if you run multiple models.
IN_RATE = 3.00 / 1_000_000
OUT_RATE = 15.00 / 1_000_000

# Cache reads cost 0.1x base input. Cache writes cost 1.25x on the 5 minute
# TTL, so two requests sharing a prefix break even (1.25 + 0.1 vs 2.0) and
# everything after that is profit. A write billed at 1x would quietly
# understate spend on every cached mission.
CACHED_RATE = 0.10 * IN_RATE
CACHE_WRITE_RATE = 1.25 * IN_RATE


class MissionPaused(RuntimeError):
    pass


class BudgetGuard(AgentMiddleware):
    """A cost ceiling enforced before a call, not discovered after it.

    Checking spend in after_model can only ever report: the call has
    already been dispatched and billed. With a large context and a large
    max_tokens, one call can cost dollars, so a $1 ceiling could be
    overshot many times over before anything noticed. wrap_model_call
    refuses first, which is what makes this a control rather than a meter.

    The residual overshoot is one call's OUTPUT, which cannot be known in
    advance. max_output_tokens bounds it: the guard reserves that much
    output at the output rate and refuses if the reservation does not fit.
    """

    def __init__(self, ceiling_usd: float = 5.00, mission: str = "adhoc",
                 model: str = "sonnet", max_output_tokens: int = 8_000):
        super().__init__()
        self.ceiling = ceiling_usd
        self.max_output_tokens = max_output_tokens
        self.mission = mission
        self.model = model
        self.spent = 0.0
        self.calls = 0          # zero means the mission never started
        self.cache_read = 0
        self.cache_write = 0
        self.uncached_in = 0

    def add_usage(self, usage: dict) -> float:
        """Price one model call and add it to the running total.

        LangChain reports input_tokens as the true total: fresh tokens plus
        cache reads plus cache writes. Subtracting only the reads would leave
        writes priced as ordinary input, which is 1.25x, not 1x.
        """
        self.calls += 1
        details = usage.get("input_token_details") or {}
        cached = details.get("cache_read") or 0
        written = details.get("cache_creation") or 0
        fresh = max(usage.get("input_tokens", 0) - cached - written, 0)
        self.cache_read += cached
        self.cache_write += written
        self.uncached_in += fresh
        self.spent += (fresh * IN_RATE
                       + cached * CACHED_RATE
                       + written * CACHE_WRITE_RATE
                       + usage.get("output_tokens", 0) * OUT_RATE)
        return self.spent

    def cache_hit_rate(self) -> float:
        """Cache reads as a share of all input tokens.

        Writes sit in the denominator: they are input you paid a premium for
        and did not read back. A mission that only ever writes is not caching
        well, and the number should say so.
        """
        total = self.cache_read + self.cache_write + self.uncached_in
        return self.cache_read / total if total else 0.0

    def projected_cost(self, request) -> float:
        """What this call could cost at worst, before it is dispatched.

        Input is counted from the request; output is reserved at the cap.
        Approximate on purpose: a ceiling needs an estimate that is never
        wildly low, not an exact price. Every token is priced as fresh,
        so a cached call is over-estimated rather than under.
        """
        messages = list(getattr(request, "messages", None) or [])
        system = getattr(request, "system_message", None)
        if system is not None:
            messages = [system, *messages]
        try:
            tokens = count_tokens_approximately(messages)
        except (TypeError, ValueError):
            tokens = 0
        return tokens * IN_RATE + self.max_output_tokens * OUT_RATE

    def single_call_floor(self) -> float:
        """The least a call can be projected to cost.

        The reservation for output is unconditional, so a ceiling below it
        refuses every call including a two token prompt. That is a real
        cliff and it deserves its own message rather than a confusing
        claim that a tiny prompt "could cost" twelve cents.
        """
        return self.max_output_tokens * OUT_RATE

    def wrap_model_call(self, request, handler):
        """Refuse before dispatch. This is the actual circuit breaker."""
        floor = self.single_call_floor()
        if self.ceiling < floor:
            raise MissionPaused(
                f"ceiling ${self.ceiling:.2f} is below the ${floor:.2f} "
                f"floor for a single call (max_output_tokens="
                f"{self.max_output_tokens:,} at ${OUT_RATE * 1e6:.2f}/MTok), "
                f"so no call can ever be dispatched. Raise the ceiling "
                f"above ${floor:.2f}, or lower max_output_tokens.")
        if self.spent >= self.ceiling:
            raise MissionPaused(
                f"ceiling ${self.ceiling:.2f} already reached at "
                f"${self.spent:.2f}; refusing to dispatch another call")
        projected = self.projected_cost(request)
        if self.spent + projected > self.ceiling:
            raise MissionPaused(
                f"next call could cost ${projected:.4f}, which would take "
                f"${self.spent:.4f} past the ${self.ceiling:.2f} ceiling; "
                f"refused before dispatch")
        return handler(request)

    def after_model(self, state, runtime=None):
        msg = state["messages"][-1]
        usage = getattr(msg, "usage_metadata", None)
        if not usage:
            return None
        before = self.spent
        total = self.add_usage(usage)
        ledger.record_call(self.mission, self.model, usage, total - before)
        if total > self.ceiling:
            # Backstop. wrap_model_call should have refused this call, so
            # reaching here means the estimate was low; state is
            # checkpointed by run.py, so resuming later is free.
            raise MissionPaused(
                f"ceiling ${self.ceiling:.2f} hit at ${self.spent:.2f}; "
                f"cache hit rate {self.cache_hit_rate():.0%}")
        return None
