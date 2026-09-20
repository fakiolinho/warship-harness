"""The ledger and the four numbers. Deterministic: no model in the loop."""
import finops
from harness import ledger


def _two_missions():
    ledger.record_call("m1", "sonnet",
                       {"input_tokens": 1000, "output_tokens": 50,
                        "input_token_details": {"cache_read": 800}}, 0.40)
    ledger.record_outcome("m1", resolved=True, steps_done=3, interventions=0)
    ledger.record_call("m2", "sonnet",
                       {"input_tokens": 500, "output_tokens": 10}, 1.60)
    ledger.record_outcome("m2", resolved=False, steps_done=0, interventions=2)


def test_the_four_numbers(isolated_ledger):
    _two_missions()
    a = finops.analyze(ledger.read())
    assert a["task_success_rate"] == 0.5
    assert a["cost_per_resolved_task"] == 2.00      # all spend / one win
    assert a["cache_hit_rate"] == 800 / 1500
    assert a["interventions_per_mission"] == 1.0
    assert a["total_cost"] == 2.00


def test_cost_per_resolved_task_charges_failures_to_the_wins(isolated_ledger):
    """The failed mission's spend is real money; it belongs in the ratio."""
    _two_missions()
    a = finops.analyze(ledger.read())
    assert a["cost_per_resolved_task"] > a["missions"]["m1"]["cost"]


def test_quadrants(isolated_ledger):
    assert finops.quadrant(
        {"cost": 2.0, "steps_done": 0, "resolved": False}) == "LEAK"
    assert finops.quadrant(
        {"cost": 0.1, "steps_done": 3, "resolved": True}) == "CHEAP WIN"
    assert finops.quadrant(
        {"cost": 2.0, "steps_done": 3, "resolved": True}) == "VELOCITY"
    assert finops.quadrant(
        {"cost": 2.0, "steps_done": 3, "resolved": False}) == "VELOCITY THEATRE"
    assert finops.quadrant(
        {"cost": 0.1, "steps_done": 0, "resolved": False}) == "IDLE"


def test_empty_ledger_reports_nothing_rather_than_infinity(isolated_ledger):
    a = finops.analyze(ledger.read())
    assert a["task_success_rate"] == 0.0
    assert "inf" not in finops.render(a)
    assert "No missions in the ledger yet" in finops.render(a)


def test_a_half_written_row_does_not_blind_the_report(isolated_ledger):
    """A killed process can leave a partial line. Skip it, do not crash."""
    _two_missions()
    with isolated_ledger.open("a") as f:
        f.write('{"kind": "call", "mission"\n')
    assert len(ledger.read()) == 4
    assert finops.analyze(ledger.read())["task_success_rate"] == 0.5


def test_render_lists_every_mission(isolated_ledger):
    _two_missions()
    report = finops.render(finops.analyze(ledger.read()))
    assert "m1" in report and "m2" in report
    assert "cost per resolved task" in report


def test_ledger_path_is_redirectable(isolated_ledger):
    ledger.record_outcome("m", True, 1, 0)
    assert isolated_ledger.exists()
    assert ledger.path() == isolated_ledger
