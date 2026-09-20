"""Budget circuit breaker: a cost ceiling per mission that pauses instead of burning."""
from langchain.agents.middleware import AgentMiddleware

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
    def __init__(self, ceiling_usd: float = 5.00, mission: str = "adhoc",
                 model: str = "sonnet"):
        super().__init__()
        self.ceiling = ceiling_usd
        self.mission = mission
        self.model = model
        self.spent = 0.0
        self.cache_read = 0
        self.cache_write = 0
        self.uncached_in = 0

    def add_usage(self, usage: dict) -> float:
        """Price one model call and add it to the running total.

        LangChain reports input_tokens as the true total: fresh tokens plus
        cache reads plus cache writes. Subtracting only the reads would leave
        writes priced as ordinary input, which is 1.25x, not 1x.
        """
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

    def after_model(self, state, runtime=None):
        msg = state["messages"][-1]
        usage = getattr(msg, "usage_metadata", None)
        if not usage:
            return None
        before = self.spent
        total = self.add_usage(usage)
        ledger.record_call(self.mission, self.model, usage, total - before)
        if total > self.ceiling:
            # State is checkpointed by run.py, so resuming later is free.
            raise MissionPaused(
                f"ceiling ${self.ceiling:.2f} hit at ${self.spent:.2f}; "
                f"cache hit rate {self.cache_hit_rate():.0%}")
        return None
