"""Prompt caching must actually be requested, not merely designed for.

Anthropic caches nothing without a cache_control breakpoint. Without one
the hit rate is structurally 0% no matter how stable the prefix is, and the
headline FinOps number reads like a regression instead of an unset switch.
"""

from langchain_core.messages import HumanMessage, SystemMessage

import agent as agent_module
import finops
from harness import BudgetGuard


def test_the_default_model_requests_caching():
    m = agent_module.default_model()
    assert m.model_kwargs["cache_control"] == {"type": "ephemeral"}


def test_the_breakpoint_reaches_the_request_payload():
    """The real check: langchain must forward it to the wire format."""
    m = agent_module.default_model()
    payload = m._get_request_payload(
        [SystemMessage(content="stable prefix"), HumanMessage(content="go")]
    )
    assert payload.get("cache_control") == {"type": "ephemeral"}


def test_the_model_id_prefix_is_stripped():
    """DEFAULT_MODEL carries langchain's 'anthropic:' provider prefix,
    which ChatAnthropic itself must not receive."""
    assert agent_module.default_model("anthropic:claude-sonnet-4-5").model == (
        "claude-sonnet-4-5"
    )


def test_build_agent_upgrades_a_model_id_to_a_caching_model(mission, tmp_path):
    """A plain string must not quietly opt out of caching."""
    captured = {}
    real = agent_module.create_agent

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    agent_module.create_agent = spy
    try:
        agent_module.build_agent(
            mission, BudgetGuard(mission="m"), model="anthropic:claude-sonnet-4-5"
        )
    finally:
        agent_module.create_agent = real
    assert captured["model"].model_kwargs["cache_control"]


def test_an_injected_model_is_left_alone(mission):
    """Tests and other providers pass an instance; do not rewrap it."""
    from conftest import ScriptedModel, ai

    model = ScriptedModel(script=[ai("hi")], calls=[])
    agent, _ = agent_module.build_agent(
        mission, BudgetGuard(mission="m"), model=model, compaction_model=None
    )
    assert agent is not None


def test_report_says_caching_is_off_rather_than_just_showing_zero():
    a = {"cache_hit_rate": 0.0, "cache_written_tokens": 0}
    assert "caching is not enabled" in finops.cache_note(a)


def test_report_distinguishes_writes_that_are_never_read():
    """Zero reads with writes is a different bug: a drifting prefix."""
    a = {"cache_hit_rate": 0.0, "cache_written_tokens": 5000}
    note = finops.cache_note(a)
    assert "not being read back" in note
    assert "caching is not enabled" not in note


def test_no_note_when_caching_is_working():
    assert finops.cache_note({"cache_hit_rate": 0.8, "cache_written_tokens": 100}) == ""
