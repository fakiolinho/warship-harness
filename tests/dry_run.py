"""A full mission end to end against a scripted model. No API key, no network.

    python tests/dry_run.py

This is what CI runs to prove the entrypoint works, and what you can run
locally to watch the harness behave before you spend a cent on a real model.

The script is a mission that tries something the gate refuses. The point is
to see the refusal happen, and to see the mission carry on afterwards.
"""

import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from conftest import ScriptedModel, ai, call  # noqa: E402

import finops  # noqa: E402
import run as run_module  # noqa: E402
from harness import ledger, state  # noqa: E402

BRIEF = """# Mission: repo health check (dry run)

Work inside the current directory only.

1. Count the Python files in the workspace.
2. Try to clear the workspace, which the gate should refuse.
3. Report that the harness held.

State STEP <n> DONE: <summary> after each step.
"""

SCRIPT = [
    ai(
        "Counting the Python files.",
        [call("run_command", {"command": "ls *.py | wc -l"}, "c1")],
    ),
    ai(
        "STEP 1 DONE: counted the Python files",
        [call("run_command", {"command": "rm -rf ."}, "c2")],
    ),
    ai(
        "STEP 2 DONE: the gate refused the destructive command",
        [call("read_file", {"path": "keep.txt"}, "c3")],
    ),
    ai("STEP 3 DONE: workspace intact, harness held"),
]


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        mission = root / "missions" / "dryrun"
        mission.mkdir(parents=True)
        (mission / "mission.md").write_text(BRIEF)
        (mission / "keep.txt").write_text("this file must survive\n")
        (mission / "sample.py").write_text("print('hi')\n")

        os.environ["WARSHIP_LEDGER"] = str(root / "ledger.jsonl")
        os.chdir(mission)

        print("=" * 62)
        print("DRY RUN: full mission, scripted model, no API key")
        print("=" * 62)
        run_module.main(
            mission, ceiling_usd=5.00, model=ScriptedModel(script=SCRIPT, calls=[])
        )

        steps = state.read_steps(mission)
        survived = (mission / "keep.txt").exists()
        report = finops.analyze(ledger.read())

        print("\n" + "=" * 62)
        print(finops.render(report))
        print("=" * 62)

        problems = []
        if len(steps) != 3:
            problems.append(f"expected 3 checkpointed steps, got {len(steps)}")
        if not survived:
            problems.append("the gate let a destructive command through")
        if not report["missions"]["dryrun"]["resolved"]:
            problems.append("a finished mission was not recorded as resolved")
        if problems:
            for p in problems:
                print(f"FAIL: {p}", file=sys.stderr)
            return 1

        print(
            "\nOK: 3/3 steps checkpointed, gate blocked `rm -rf .`, "
            "workspace intact, mission recorded as resolved"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
