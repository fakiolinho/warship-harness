"""The judge grades transcripts; the report stays deterministic.

Every test here runs against a scripted model: a judge that needed an API
key could not run in CI, and the parsing is where the real risk lives.
"""
import pytest
from conftest import ScriptedModel
from langchain_core.messages import AIMessage

import finops
import run as run_module
from harness import judge, ledger


def _judge_model(payload: str):
    return ScriptedModel(
        script=[AIMessage(content=payload,
                          usage_metadata={"input_tokens": 900,
                                          "output_tokens": 60,
                                          "total_tokens": 960})],
        calls=[])


GOOD = '{"resolved": true, "score": 0.9, "reasoning": "all three ran", "failed_steps": []}'
BAD = '{"resolved": false, "score": 0.3, "reasoning": "step 2 read truncated output", "failed_steps": [2]}'


def test_parses_a_clean_verdict():
    v, usage = judge.judge_mission("brief", "transcript", _judge_model(GOOD), "m")
    assert v.resolved is True and v.score == 0.9
    assert usage["input_tokens"] == 900


def test_parses_a_fenced_verdict():
    """Models wrap JSON in fences whether you ask them to or not."""
    v, _ = judge.judge_mission(
        "b", "t", _judge_model(f"Here:\n```json\n{GOOD}\n```"), "m")
    assert v.resolved is True


def test_parses_json_containing_braces_in_a_string():
    """Counting braces breaks here; the decoder must not."""
    raw = '{"resolved": false, "score": 0.1, "reasoning": "saw {weird} output"}'
    assert judge.parse_verdict(raw)["reasoning"] == "saw {weird} output"


@pytest.mark.parametrize("junk", ["no json at all", "[1, 2, 3]", "{unclosed"])
def test_unparseable_responses_raise_clearly(junk):
    with pytest.raises(ValueError):
        judge.parse_verdict(junk)


def test_a_missing_resolved_field_is_not_a_pass():
    """Absent evidence must never read as success."""
    v, _ = judge.judge_mission("b", "t", _judge_model('{"score": 0.9}'), "m")
    assert v.resolved is False


def test_a_nonsense_score_is_clamped_not_fatal():
    v, _ = judge.judge_mission(
        "b", "t", _judge_model('{"resolved": true, "score": "banana"}'), "m")
    assert v.score == 0.0 and v.resolved is True
    v2, _ = judge.judge_mission(
        "b", "t", _judge_model('{"resolved": true, "score": 7}'), "m")
    assert v2.score == 1.0


def test_the_rubric_version_is_recorded():
    """A rubric change makes old verdicts a different metric."""
    v, _ = judge.judge_mission("b", "t", _judge_model(GOOD), "sonnet")
    assert v.rubric == judge.RUBRIC_VERSION and v.model == "sonnet"


def test_the_transcript_is_truncated_before_it_is_sent():
    model = _judge_model(GOOD)
    judge.judge_mission("b", "x" * 200_000, model, "m")
    assert len(str(model.calls[0])) < 100_000


def test_grade_records_the_verdict_and_its_cost(mission, isolated_ledger):
    v = run_module.grade(mission, ["transcript"], _judge_model(BAD), "sonnet")
    assert v is not None and v.failed_steps == [2]
    rows = [r for r in ledger.read() if r["kind"] == "judge"]
    assert len(rows) == 1 and rows[0]["cost"] > 0
    assert rows[0]["rubric"] == judge.RUBRIC_VERSION


def test_a_broken_judge_never_loses_the_mission(mission, isolated_ledger):
    """Losing a verdict is survivable; losing the outcome row is not."""
    class Exploding:
        model = "boom"

        def invoke(self, _):
            raise RuntimeError("judge API down")

    assert run_module.grade(mission, ["t"], Exploding(), "boom") is None


def test_judge_spend_stays_out_of_mission_spend(isolated_ledger):
    """Pooling them would inflate cost per resolved task with the cost of
    asking whether it resolved."""
    ledger.record_call("m", "sonnet",
                       {"input_tokens": 100, "output_tokens": 10}, 1.00)
    v = judge.Verdict(resolved=True, score=0.9, reasoning="ok", failed_steps=[])
    ledger.record_judgement("m", v, {"input_tokens": 50, "output_tokens": 5}, 0.25)
    ledger.record_outcome("m", True, 3, 0, resolved_by="judge")
    a = finops.analyze(ledger.read())
    assert a["missions"]["m"]["cost"] == 1.00        # not 1.25
    assert a["judge_cost"] == 0.25
    assert a["cost_per_resolved_task"] == 1.00
    assert a["judged_missions"] == 1


def test_the_report_flags_verdicts_that_are_only_step_counts(isolated_ledger):
    ledger.record_call("m", "s", {"input_tokens": 10, "output_tokens": 1}, 0.01)
    ledger.record_outcome("m", True, 3, 0)
    assert "step count proxy" in finops.render(finops.analyze(ledger.read()))


def test_the_report_shows_the_judge_score(isolated_ledger):
    ledger.record_call("m", "s", {"input_tokens": 10, "output_tokens": 1}, 0.01)
    v = judge.Verdict(resolved=True, score=0.82, reasoning="ok", failed_steps=[])
    ledger.record_judgement("m", v, {"input_tokens": 5, "output_tokens": 1}, 0.001)
    ledger.record_outcome("m", True, 3, 0, resolved_by="judge")
    report = finops.render(finops.analyze(ledger.read()))
    assert "judge 0.82" in report
    assert "step count proxy" not in report


def test_a_long_transcript_keeps_the_ending():
    """Keeping only the first N chars grades a mission on its opening.
    Agents fail at the end, and those are the expensive missions."""
    body = "\n".join(f"[AIMessage] STEP {i} DONE: fine and padded out"
                     for i in range(1, 1500))
    elided = judge.elide(body + "\n[ToolMessage] FATAL: nothing deployed")
    assert "FATAL: nothing deployed" in elided
    assert "STEP 1 DONE" in elided
    assert len(elided) < judge.MAX_TRANSCRIPT_CHARS * 1.05


def test_a_short_transcript_is_untouched():
    assert judge.elide("short") == "short"


def test_elision_says_what_it_dropped():
    """Silent truncation is how a judge grades half a mission and says
    nothing about it."""
    out = judge.elide("x" * 100_000)
    assert "elided from the middle" in out


def test_the_judge_actually_receives_both_ends():
    from conftest import ScriptedModel
    from langchain_core.messages import AIMessage
    model = ScriptedModel(
        script=[AIMessage(content=GOOD, usage_metadata={
            "input_tokens": 10, "output_tokens": 1, "total_tokens": 11})],
        calls=[])
    body = ("OPENING-MARKER\n" + "filler line\n" * 20_000 + "CLOSING-MARKER")
    judge.judge_mission("brief", body, model, "m")
    sent = str(model.calls[0])
    assert "OPENING-MARKER" in sent and "CLOSING-MARKER" in sent
