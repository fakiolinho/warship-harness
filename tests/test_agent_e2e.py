"""End to end through the real create_agent graph, with a scripted model.

No API key, no network. These are the tests that would have caught a
middleware signature drift after a LangChain upgrade.
"""
import pytest
from conftest import ScriptedModel, ai, call

import agent as agent_module
import finops
import run as run_module
from harness import BudgetGuard, ledger, state


def _run(mission, model, ceiling=5.00, approver=lambda n, a: False):
    agent_module.set_workspace(mission)
    budget = BudgetGuard(ceiling_usd=ceiling, mission=mission.name)
    agent, gate = agent_module.build_agent(
        mission, budget, model=model, approver=approver,
        compaction_model=None)      # no summarizer: it would need a real model
    steps = []
    for event in agent.stream({"messages": [("user", state.resume_prompt(mission))]},
                              stream_mode="values"):
        msg = event["messages"][-1]
        text = str(getattr(msg, "text", None) or msg.content)
        steps.append(text)
        for m in run_module.STEP_RE.finditer(text):
            state.checkpoint(mission, int(m.group(1)), m.group(2).strip(), [])
    return budget, gate, steps


def test_a_clean_run_checkpoints_every_step(mission, isolated_ledger):
    model = ScriptedModel(script=[
        ai("STEP 1 DONE: first", [call("run_command", {"command": "echo a"})]),
        ai("STEP 2 DONE: second", [call("run_command", {"command": "echo b"}, "c2")]),
        ai("STEP 3 DONE: third"),
    ], calls=[])
    budget, gate, _ = _run(mission, model)
    assert [s["n"] for s in state.read_steps(mission)] == [1, 2, 3]
    assert budget.spent > 0
    assert gate.interventions == 0


def test_a_denied_command_never_executes(mission, isolated_ledger):
    """The model asks for rm -rf; the gate answers, not the model."""
    canary = mission / "canary.txt"
    canary.write_text("still here")
    model = ScriptedModel(script=[
        ai("deleting", [call("run_command", {"command": f"rm -rf {canary}"})]),
        ai("STEP 1 DONE: blocked"),
    ], calls=[])
    _run(mission, model)
    assert canary.exists() and canary.read_text() == "still here"


def test_a_gated_command_counts_as_an_intervention(mission, isolated_ledger):
    model = ScriptedModel(script=[
        ai("pushing", [call("run_command", {"command": "git push origin main"})]),
        ai("STEP 1 DONE: asked"),
    ], calls=[])
    _, gate, _ = _run(mission, model, approver=lambda n, a: True)
    assert gate.interventions == 1


def test_oversized_tool_output_is_persisted_not_inlined(mission, isolated_ledger):
    model = ScriptedModel(script=[
        ai("reading", [call("run_command",
                            {"command": "python3 -c \"print('x'*20000)\""})]),
        ai("STEP 1 DONE: read it"),
    ], calls=[])
    _run(mission, model)
    artifacts = list((mission / "artifacts").glob("*.txt"))
    assert artifacts and len(artifacts[0].read_text()) > 20000


def test_the_budget_ceiling_stops_a_runaway(mission, isolated_ledger):
    """Ten scripted steps, a ceiling that trips on the first call."""
    model = ScriptedModel(
        script=[ai(f"STEP {i} DONE: step {i}") for i in range(1, 11)],
        calls=[])
    try:
        _run(mission, model, ceiling=0.0001)
    except Exception as e:
        assert type(e).__name__ == "MissionPaused" or "MissionPaused" in str(e)
    assert len(model.calls) < 10       # it stopped early, it did not finish


def test_a_resumed_run_is_told_what_is_already_done(mission, isolated_ledger):
    state.checkpoint(mission, 1, "first", [])
    model = ScriptedModel(script=[ai("STEP 2 DONE: second")], calls=[])
    _run(mission, model)
    first_prompt = str(model.calls[0][-1].content)
    assert "do not redo" in first_prompt
    assert "step 1: first" in first_prompt


def test_the_cacheable_prefix_is_identical_across_runs(mission, isolated_ledger):
    """Cache hit rate is the dominant cost lever; the prefix must not drift."""
    model_a = ScriptedModel(script=[ai("STEP 1 DONE: a")], calls=[])
    _run(mission, model_a)
    model_b = ScriptedModel(script=[ai("STEP 2 DONE: b")], calls=[])
    _run(mission, model_b)
    assert str(model_a.calls[0][0].content) == str(model_b.calls[0][0].content)


def test_run_main_records_a_finished_mission_as_resolved(
        mission, isolated_ledger, monkeypatch):
    """The real entrypoint: three steps asked for, three delivered."""
    monkeypatch.chdir(mission)
    model = ScriptedModel(script=[
        ai("STEP 1 DONE: first", [call("run_command", {"command": "echo a"})]),
        ai("STEP 2 DONE: second", [call("run_command", {"command": "echo b"}, "c2")]),
        ai("STEP 3 DONE: third"),
    ], calls=[])
    assert run_module.main(mission, ceiling_usd=5.00, model=model) == 0
    a = finops.analyze(ledger.read())
    assert a["task_success_rate"] == 1.0
    assert a["missions"]["demo"]["steps_done"] == 3
    assert a["missions"]["demo"]["resolved"] is True


def test_run_main_records_a_short_mission_as_unresolved(
        mission, isolated_ledger, monkeypatch):
    """One step done out of the three the brief asked for is not a win."""
    monkeypatch.chdir(mission)
    model = ScriptedModel(script=[ai("STEP 1 DONE: only one")], calls=[])
    run_module.main(mission, ceiling_usd=5.00, model=model)
    a = finops.analyze(ledger.read())
    assert a["missions"]["demo"]["resolved"] is False
    assert a["task_success_rate"] == 0.0


def test_expected_steps_is_read_from_the_brief(mission, tmp_path):
    assert run_module.expected_steps(mission) == 3
    solo = tmp_path / "solo"
    solo.mkdir()
    (solo / "mission.md").write_text("Just do the thing.\n")
    assert run_module.expected_steps(solo) == 1


class _DeadModel(ScriptedModel):
    """A model that fails the way a missing API key fails."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise TypeError(
            "Anthropic authentication failed: no API key or authorization "
            "credentials were provided. Set the ANTHROPIC_API_KEY ...")


def test_a_setup_failure_is_not_recorded_as_a_failed_mission(
        mission, isolated_ledger, monkeypatch):
    """A missing API key put a permanent 'resolved: false' row in the
    ledger, dragging task success rate down forever. Nothing was
    dispatched, so there is no mission result to record."""
    monkeypatch.chdir(mission)
    assert run_module.main(mission, model=_DeadModel(script=[], calls=[])) == 1
    assert [r for r in ledger.read() if r["kind"] == "outcome"] == []


def test_a_setup_failure_explains_itself(mission, isolated_ledger, monkeypatch,
                                         capsys):
    monkeypatch.chdir(mission)
    run_module.main(mission, model=_DeadModel(script=[], calls=[]))
    out = capsys.readouterr().out
    assert "never started" in out
    assert "ANTHROPIC_API_KEY" in out
    assert "Traceback" not in out


def test_a_failure_after_the_mission_started_is_not_swallowed(
        mission, isolated_ledger, monkeypatch):
    """Only a mission that never dispatched is a setup problem. A real
    failure mid run must still surface."""
    class _FlakyModel(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if self.calls:
                raise RuntimeError("upstream exploded mid mission")
            return super()._generate(messages, stop, run_manager, **kwargs)

    monkeypatch.chdir(mission)
    # A tool call, so the graph comes back for a second model call.
    model = _FlakyModel(
        script=[ai("STEP 1 DONE: one",
                   [call("run_command", {"command": "echo hi"})])],
        calls=[])
    with pytest.raises(RuntimeError, match="exploded"):
        run_module.main(mission, model=model)


@pytest.mark.parametrize("message,wanted", [
    ("Anthropic authentication failed: no API key", "ANTHROPIC_API_KEY"),
    ("rate limit exceeded", "rate limited"),
])
def test_diagnose_turns_library_errors_into_advice(message, wanted):
    assert wanted in run_module._diagnose(RuntimeError(message))
