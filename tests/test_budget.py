"""The circuit breaker: a ceiling that pauses instead of burning."""
import pytest

from harness import MissionPaused
from harness.budget import (
    CACHE_WRITE_RATE,
    CACHED_RATE,
    IN_RATE,
    OUT_RATE,
    BudgetGuard,
)


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


def test_cache_writes_are_priced_at_the_write_premium():
    """input_tokens is the true total, so writes must be subtracted out too.
    Left in, they bill at 1x when a cache write actually costs 1.25x."""
    g = BudgetGuard(ceiling_usd=100)
    g.add_usage({"input_tokens": 2000, "output_tokens": 0,
                 "input_token_details": {"cache_read": 1000,
                                         "cache_creation": 500}})
    expected = 500 * IN_RATE + 1000 * CACHED_RATE + 500 * CACHE_WRITE_RATE
    assert g.spent == pytest.approx(expected)


def test_a_cache_write_costs_more_than_fresh_input():
    assert CACHE_WRITE_RATE > IN_RATE > CACHED_RATE


def test_two_requests_sharing_a_prefix_beat_paying_twice():
    """The 5 minute TTL break even: write once, read once, versus two
    uncached calls. If this inverts, caching is a pure loss."""
    tokens = 10_000
    cached_path = tokens * CACHE_WRITE_RATE + tokens * CACHED_RATE
    uncached_path = 2 * tokens * IN_RATE
    assert cached_path < uncached_path


def test_writes_count_against_the_hit_rate():
    """Writing and never reading is not caching well; the number says so."""
    g = BudgetGuard(ceiling_usd=100)
    g.add_usage({"input_tokens": 1000, "output_tokens": 0,
                 "input_token_details": {"cache_creation": 1000}})
    assert g.cache_hit_rate() == 0.0
    assert g.cache_write == 1000


def test_usage_with_no_cache_keys_is_unchanged():
    """The uncached path must keep costing exactly what it did before."""
    g = BudgetGuard(ceiling_usd=100)
    g.add_usage({"input_tokens": 1000, "output_tokens": 100})
    assert g.spent == pytest.approx(1000 * IN_RATE + 100 * OUT_RATE)


def test_explicit_none_cache_details_are_treated_as_zero():
    """Anthropic sends null, not 0, when a call did not touch the cache."""
    g = BudgetGuard(ceiling_usd=100)
    g.add_usage({"input_tokens": 1000, "output_tokens": 0,
                 "input_token_details": {"cache_read": None,
                                         "cache_creation": None}})
    assert g.spent == pytest.approx(1000 * IN_RATE)


class _Req:
    """Minimal ModelRequest stand-in: messages plus an optional system."""

    def __init__(self, messages, system_message=None):
        self.messages = messages
        self.system_message = system_message


def test_the_ceiling_refuses_before_dispatch():
    """after_model can only report; the call is already billed by then."""
    from langchain_core.messages import HumanMessage
    dispatched = []
    # Above the single-call floor, so this exercises the projection rather
    # than the "ceiling is structurally too low" branch.
    g = BudgetGuard(ceiling_usd=0.20, mission="m")
    with pytest.raises(MissionPaused, match="refused before dispatch"):
        g.wrap_model_call(_Req([HumanMessage(content="x" * 400_000)]),
                          lambda r: dispatched.append(r))
    assert dispatched == []
    assert g.spent == 0.0          # nothing was spent, not merely noticed


def test_an_affordable_call_is_dispatched():
    from langchain_core.messages import HumanMessage
    g = BudgetGuard(ceiling_usd=100.0, mission="m")
    assert g.wrap_model_call(_Req([HumanMessage(content="hi")]),
                             lambda r: "ran") == "ran"


def test_a_spent_out_budget_refuses_immediately():
    from langchain_core.messages import HumanMessage
    g = BudgetGuard(ceiling_usd=1.00, mission="m")
    g.spent = 1.00
    with pytest.raises(MissionPaused, match="already reached"):
        g.wrap_model_call(_Req([HumanMessage(content="hi")]), lambda r: "ran")


def test_the_reserved_output_is_part_of_the_projection():
    """The unknowable half of a call's cost is its output; reserve it or
    the ceiling can still be overshot by a long generation."""
    from langchain_core.messages import HumanMessage
    req = _Req([HumanMessage(content="hi")])
    small = BudgetGuard(ceiling_usd=100, max_output_tokens=1_000)
    large = BudgetGuard(ceiling_usd=100, max_output_tokens=100_000)
    assert large.projected_cost(req) > small.projected_cost(req)


def test_the_system_message_counts_toward_the_projection():
    from langchain_core.messages import HumanMessage, SystemMessage
    g = BudgetGuard(ceiling_usd=100)
    bare = g.projected_cost(_Req([HumanMessage(content="hi")]))
    withsys = g.projected_cost(
        _Req([HumanMessage(content="hi")],
             SystemMessage(content="a long stable system prefix " * 200)))
    assert withsys > bare


def test_a_malformed_request_does_not_crash_the_guard():
    """An estimate that cannot be computed must not take down a mission."""
    g = BudgetGuard(ceiling_usd=100)
    assert g.projected_cost(_Req(None)) >= 0


def test_a_ceiling_below_the_single_call_floor_says_so():
    """Otherwise a $0.05 ceiling refuses a two token prompt while claiming
    it "could cost" twelve cents, which is true and useless."""
    from langchain_core.messages import HumanMessage
    g = BudgetGuard(ceiling_usd=0.05, max_output_tokens=8_000)
    with pytest.raises(MissionPaused, match="below the .* floor"):
        g.wrap_model_call(_Req([HumanMessage(content="hi")]), lambda r: "ran")


def test_the_floor_follows_max_output_tokens():
    assert BudgetGuard(max_output_tokens=1_000).single_call_floor() < \
        BudgetGuard(max_output_tokens=8_000).single_call_floor()


def test_a_small_ceiling_works_once_the_reservation_is_small():
    """The floor is a consequence of the reservation, not a hard minimum."""
    from langchain_core.messages import HumanMessage
    g = BudgetGuard(ceiling_usd=0.05, max_output_tokens=500)
    assert g.wrap_model_call(_Req([HumanMessage(content="hi")]),
                             lambda r: "ran") == "ran"
