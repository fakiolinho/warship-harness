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
from harness import BudgetGuard, MissionPaused, judge, ledger, state

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


def grade(mission_dir: pathlib.Path, transcript: list[str],
          judge_model, model_name: str) -> judge.Verdict | None:
    """Ask the judge whether the mission actually did what the brief asked.

    Never fatal. A judge that errors leaves the step count proxy standing,
    because losing the verdict is better than losing the mission record.
    """
    brief = (mission_dir / "mission.md").read_text()
    try:
        verdict, usage = judge.judge_mission(
            brief, "\n".join(transcript), judge_model, model_name)
    except Exception as why:          # noqa: BLE001 - never lose the outcome
        print(f"\njudge unavailable ({type(why).__name__}: {why}); "
              "falling back to the step count")
        return None
    meter = BudgetGuard(ceiling_usd=float("inf"), mission=mission_dir.name)
    ledger.record_judgement(mission_dir.name, verdict, usage,
                            meter.add_usage(usage))
    mark = "resolved" if verdict.resolved else "NOT resolved"
    print(f"\njudge ({verdict.model}, rubric {verdict.rubric}): {mark}, "
          f"score {verdict.score:.2f}")
    if verdict.failed_steps:
        print(f"  steps not genuinely completed: {verdict.failed_steps}")
    print(f"  {verdict.reasoning}")
    return verdict


def main(mission_dir: pathlib.Path, ceiling_usd: float = DEFAULT_CEILING_USD,
         model: str | object = agent_module.DEFAULT_MODEL,
         judge_model: object | None = None) -> int:
    if not (mission_dir / "mission.md").is_file():
        sys.exit(f"error: no mission brief at {mission_dir / 'mission.md'}")

    agent_module.set_workspace(pathlib.Path.cwd())
    budget = BudgetGuard(ceiling_usd=ceiling_usd, mission=mission_dir.name)
    agent, gate = build_agent(mission_dir, budget, model=model)
    prompt = state.resume_prompt(mission_dir)
    wanted = expected_steps(mission_dir)
    seen: set[str] = set()
    transcript: list[str] = []
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
            transcript.append(f"[{type(msg).__name__}] {text}")
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
        resolved, resolved_by = steps >= wanted, "steps"
        if judge_model is not None:
            verdict = grade(mission_dir, transcript, judge_model,
                            getattr(judge_model, "model", "unknown"))
            if verdict is not None:
                resolved, resolved_by = verdict.resolved, "judge"
        ledger.record_outcome(mission_dir.name, resolved=resolved,
                              steps_done=steps,
                              interventions=gate.interventions,
                              resolved_by=resolved_by)
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
    p.add_argument("--judge", nargs="?", const=agent_module.DEFAULT_MODEL,
                   default=None, metavar="MODEL",
                   help="grade the finished mission with an LLM judge "
                        "instead of counting STEP lines. Costs one extra "
                        "model call per mission, recorded in the ledger.")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(
        args.mission, args.ceiling, args.model,
        agent_module.default_model(args.judge) if args.judge else None))
