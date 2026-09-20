"""One runnable check per harness component. No frameworks, no API key.

python selfcheck.py  ->  prints OK lines or throws.

This is the smoke test: fast, dependency free, safe to run anywhere.
The full suite lives in tests/ and needs pytest.
"""
import os
import pathlib
import tempfile

from harness import memory, state
from harness.budget import BudgetGuard
from harness.context import MAX_INLINE_CHARS, bounded
from harness.gate import decide

# gate: deny wins, ask gates, normal passes, and case does not matter
assert decide("run_command", {"command": "rm -rf /"}) == "deny"
assert decide("run_command", {"command": "RM -RF /"}) == "deny"
assert decide("run_command", {"command": "DROP TABLE users"}) == "deny"
assert decide("run_command", {"command": "git push origin main"}) == "ask"
assert decide("read_file", {"path": "notes.md"}) == "allow"

with tempfile.TemporaryDirectory() as td:
    tmp = pathlib.Path(td)

    # bounded: small passes through, big is persisted with a stub
    assert bounded("small", tmp) == "small"
    stub = bounded("x" * (MAX_INLINE_CHARS + 1), tmp)
    assert "saved to" in stub and len(stub) < MAX_INLINE_CHARS
    assert len(list(tmp.glob("*.txt"))) == 1

    # state: checkpoint then resume mentions the finished step
    mission = tmp / "m1"
    mission.mkdir()
    (mission / "mission.md").write_text("brief")
    state.checkpoint(mission, 1, "listed files", [])
    resumed = state.resume_prompt(mission)
    assert resumed.startswith("brief")          # stable prefix first
    assert "step 1: listed files" in resumed

    # state: re-recording a step replaces it, it does not pile up
    state.checkpoint(mission, 1, "listed files", [])
    assert len(state.read_steps(mission)) == 1

    # memory: pending -> approve -> load
    mem = tmp / "memory"
    memory.submit_for_review("- tests are flaky on CI", mem)
    memory.approve(mem)
    assert "flaky" in memory.load(mem)

# budget: ceiling triggers, cache rate computed
g = BudgetGuard(ceiling_usd=0.01)
g.add_usage({"input_tokens": 1000, "output_tokens": 100,
             "input_token_details": {"cache_read": 900}})
assert 0 < g.spent < 0.01 and abs(g.cache_hit_rate() - 0.9) < 1e-9
g.add_usage({"input_tokens": 4_000_000, "output_tokens": 0})
assert g.spent > 0.01  # after_model would raise MissionPaused here

print("OK: gate, bounded output, state resume, memory loop, budget")

# ledger + finops: two missions in, four numbers out (isolated ledger)
with tempfile.TemporaryDirectory() as td2:
    os.environ["WARSHIP_LEDGER"] = str(pathlib.Path(td2) / "ledger.jsonl")
    import finops as F  # noqa: E402
    from harness import ledger as L  # noqa: E402
    L.record_call("m1", "sonnet", {"input_tokens": 1000, "output_tokens": 50,
                  "input_token_details": {"cache_read": 800}}, 0.40)
    L.record_outcome("m1", resolved=True, steps_done=3, interventions=0)
    L.record_call("m2", "sonnet", {"input_tokens": 500, "output_tokens": 10},
                  1.60)
    L.record_outcome("m2", resolved=False, steps_done=0, interventions=2)
    a = F.analyze(L.read())
    assert a["task_success_rate"] == 0.5
    assert abs(a["cost_per_resolved_task"] - 2.00) < 1e-9  # all spend / 1 win
    assert abs(a["cache_hit_rate"] - 800 / 1500) < 1e-9
    assert a["interventions_per_mission"] == 1.0
    assert F.quadrant(a["missions"]["m2"]) == "LEAK"
    assert "cost per resolved task" in F.render(a)
    os.environ.pop("WARSHIP_LEDGER", None)

print("OK: ledger + finops report (cost per resolved task, quadrants)")
