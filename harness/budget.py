"""Budget circuit breaker: a cost ceiling per mission that pauses instead of burning."""
from langchain.agents.middleware import AgentMiddleware

from . import ledger

# ponytail: flat Sonnet-class rates, USD per token. Pull live pricing
# from config if you run multiple models.
IN_RATE = 3.00 / 1_000_000
CACHED_RATE = 0.30 / 1_000_000
OUT_RATE = 15.00 / 1_000_000


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
        self.uncached_in = 0

    def add_usage(self, usage: dict) -> float:
        details = usage.get("input_token_details") or {}
        cached = details.get("cache_read", 0)
        fresh = usage.get("input_tokens", 0) - cached
        self.cache_read += cached
        self.uncached_in += fresh
        self.spent += (fresh * IN_RATE + cached * CACHED_RATE
                       + usage.get("output_tokens", 0) * OUT_RATE)
        return self.spent

    def cache_hit_rate(self) -> float:
        total = self.cache_read + self.uncached_in
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
