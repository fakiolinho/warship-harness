"""Run a mission: python run.py missions/demo

Crashes and budget pauses are cheap: state.json carries progress,
so the next run resumes instead of restarting.
"""
import argparse
import pathlib
import re
import sys

import agent as agent_module
from agent import build_agent
from harness import BudgetGuard, MissionPaused, ledger, state

STEP_RE = re.compile(r"STEP (\d+) DONE: (.+)")
BRIEF_STEP_RE = re.compile(r"^\s*(\d+)\.\s+\S", re.MULTILINE)
DEFAULT_CEILING_USD = 5.00


def expected_steps(mission_dir: pathlib.Path) -> int:
    """How many numbered steps the brief asks for.

    Read from the brief rather than hardcoded, so "resolved" means
    "did what this mission asked", not "did at least three things".
    """
    brief = (mission_dir / "mission.md").read_text()
    numbers = [int(n) for n in BRIEF_STEP_RE.findall(brief)]
    return max(numbers) if numbers else 1


def main(mission_dir: pathlib.Path, ceiling_usd: float = DEFAULT_CEILING_USD,
         model: str | object = agent_module.DEFAULT_MODEL) -> int:
    if not (mission_dir / "mission.md").is_file():
        sys.exit(f"error: no mission brief at {mission_dir / 'mission.md'}")

    agent_module.set_workspace(pathlib.Path.cwd())
    budget = BudgetGuard(ceiling_usd=ceiling_usd, mission=mission_dir.name)
    agent, gate = build_agent(mission_dir, budget, model=model)
    prompt = state.resume_prompt(mission_dir)
    wanted = expected_steps(mission_dir)
    seen: set[str] = set()
    try:
        for event in agent.stream({"messages": [("user", prompt)]},
                                  stream_mode="values"):
            msg = event["messages"][-1]
            # "values" replays the whole state each superstep, so the same
            # message arrives more than once. Print it once.
            key = getattr(msg, "id", None) or str(id(msg))
            if key in seen:
                continue
            seen.add(key)
            text = str(getattr(msg, "text", None) or msg.content)
            print(text[:400])
            for m in STEP_RE.finditer(text):
                state.checkpoint(mission_dir, int(m.group(1)),
                                 m.group(2).strip(), [])
    except MissionPaused as why:
        print(f"\nPAUSED: {why}\nRe-run to resume from the checkpoint.")
    except KeyboardInterrupt:
        print("\nINTERRUPTED. Re-run to resume from the checkpoint.")
    finally:
        steps = len(state.read_steps(mission_dir))
        resolved = steps >= wanted
        ledger.record_outcome(mission_dir.name, resolved=resolved,
                              steps_done=steps,
                              interventions=gate.interventions)
        print(f"\nspend ${budget.spent:.4f}, "
              f"cache hit rate {budget.cache_hit_rate():.0%}, "
              f"steps {steps}/{wanted}, interventions {gate.interventions}")
        print("run `python finops.py` for the task economics report")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run.py",
        description="Run a mission through the warship harness.")
    p.add_argument("mission", nargs="?", default="missions/demo",
                   type=pathlib.Path,
                   help="mission directory containing mission.md "
                        "(default: missions/demo)")
    p.add_argument("--ceiling", type=float, default=DEFAULT_CEILING_USD,
                   metavar="USD",
                   help=f"budget ceiling in USD before the run pauses "
                        f"(default: {DEFAULT_CEILING_USD:.2f})")
    p.add_argument("--model", default=agent_module.DEFAULT_MODEL,
                   help=f"model id (default: {agent_module.DEFAULT_MODEL})")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(args.mission, args.ceiling, args.model))
