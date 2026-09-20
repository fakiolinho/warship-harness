"""The circuit breaker: a ceiling that pauses instead of burning."""
import pytest

from harness import MissionPaused
from harness.budget import CACHED_RATE, IN_RATE, OUT_RATE, BudgetGuard


def test_cost_is_priced_per_token_class():
    g = BudgetGuard(ceiling_usd=100)
    g.add_usage({"input_tokens": 1000, "output_tokens": 100,
                 "input_token_details": {"cache_read": 900}})
    expected = 100 * IN_RATE + 900 * CACHED_RATE + 100 * OUT_RATE
    assert g.spent == pytest.approx(expected)


def test_cached_tokens_are_cheaper_than_fresh_ones():
    assert CACHED_RATE < IN_RATE


def test_cache_hit_rate():
    g = BudgetGuard(ceiling_usd=100)
    g.add_usage({"input_tokens": 1000, "output_tokens": 0,
                 "input_token_details": {"cache_read": 900}})
    assert g.cache_hit_rate() == pytest.approx(0.9)


def test_cache_hit_rate_is_zero_before_any_call():
    assert BudgetGuard().cache_hit_rate() == 0.0


def test_usage_without_cache_details_is_all_fresh():
    g = BudgetGuard(ceiling_usd=100)
    g.add_usage({"input_tokens": 1000, "output_tokens": 0})
    assert g.cache_hit_rate() == 0.0
    assert g.spent == pytest.approx(1000 * IN_RATE)


def test_spending_accumulates_across_calls():
    g = BudgetGuard(ceiling_usd=100)
    g.add_usage({"input_tokens": 1000, "output_tokens": 0})
    g.add_usage({"input_tokens": 1000, "output_tokens": 0})
    assert g.spent == pytest.approx(2000 * IN_RATE)


class _Msg:
    def __init__(self, usage):
        self.usage_metadata = usage


def test_crossing_the_ceiling_pauses_the_mission(isolated_ledger):
    g = BudgetGuard(ceiling_usd=0.001, mission="m")
    with pytest.raises(MissionPaused):
        g.after_model({"messages": [_Msg({"input_tokens": 1_000_000,
                                          "output_tokens": 0})]})


def test_staying_under_the_ceiling_does_not_pause(isolated_ledger):
    g = BudgetGuard(ceiling_usd=100, mission="m")
    assert g.after_model({"messages": [_Msg({"input_tokens": 10,
                                             "output_tokens": 1})]}) is None


def test_a_message_without_usage_is_ignored(isolated_ledger):
    g = BudgetGuard(ceiling_usd=0.0, mission="m")
    assert g.after_model({"messages": [_Msg(None)]}) is None
    assert g.spent == 0.0


def test_the_paused_call_is_still_recorded(isolated_ledger):
    """You paid for the call that tripped the ceiling; the ledger says so."""
    from harness import ledger
    g = BudgetGuard(ceiling_usd=0.001, mission="m")
    with pytest.raises(MissionPaused):
        g.after_model({"messages": [_Msg({"input_tokens": 1_000_000,
                                          "output_tokens": 0})]})
    assert [r for r in ledger.read() if r["kind"] == "call"]
