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
from harness import BudgetGuard, MissionPaused, judge, ledger, memory, state

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
    # Count the numbered steps rather than taking the highest number. A
    # brief numbered 1. then 5. asks for two things; max() would demand
    # five and the mission could never be recorded as resolved.
    return len(numbers) if numbers else 1


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


def remember(mission_dir: pathlib.Path, transcript: list[str],
             distill_model) -> pathlib.Path | None:
    """Distill the run into facts and queue them for human review.

    This is the half of the memory loop that was documented but never
    called: without it `pending.md` is never written, so nothing is ever
    there to approve and approved.md stays empty forever. Writing to
    pending is deliberate — memory lands in the system prompt of every
    later mission, so a human stays between the two.
    """
    memory_dir = mission_dir.parent / "memory"
    try:
        facts = memory.distill("\n".join(transcript), distill_model)
    except Exception as why:          # noqa: BLE001 - never lose the outcome
        print(f"\ndistill unavailable ({type(why).__name__}: {why})")
        return None
    path = memory.submit_for_review(str(facts).strip(), memory_dir)
    print(f"\nqueued for review: {path}")
    print("  read it, then approve with: python -c \"from harness import "
          "memory, pathlib; memory.approve(pathlib.Path('"
          f"{memory_dir}'))\"")
    return path


def main(mission_dir: pathlib.Path, ceiling_usd: float = DEFAULT_CEILING_USD,
         model: str | object = agent_module.DEFAULT_MODEL,
         judge_model: object | None = None,
         distill_model: object | None = None) -> int:
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
        if distill_model is not None and transcript:
            remember(mission_dir, transcript, distill_model)
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
    p.add_argument("--distill", nargs="?",
                   const=agent_module.COMPACTION_MODEL, default=None,
                   metavar="MODEL",
                   help="distill the run into facts and queue them in "
                        "memory/pending.md for human review. Without this "
                        "the memory loop never starts. Uses the cheap tier "
                        f"by default ({agent_module.COMPACTION_MODEL}).")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(
        args.mission, args.ceiling, args.model,
        agent_module.default_model(args.judge) if args.judge else None,
        agent_module.default_model(args.distill) if args.distill else None))
