"""FinOps report from the ledger: the four numbers, per mission and aggregate.

Deterministic code, no model call. The math that goes in front of a board
should not hallucinate.

    python finops.py            # prints report, writes finops_report.md
"""
import argparse
import math
import pathlib
from collections import defaultdict

from harness import ledger

HOT_SPEND_USD = 1.00    # ponytail: fixed line; percentile split once the
                        # ledger has volume.
REPORT_PATH = "finops_report.md"


def analyze(rows: list[dict]) -> dict:
    m = defaultdict(lambda: {"cost": 0.0, "in": 0, "cached": 0, "written": 0,
                             "out": 0, "calls": 0, "resolved": None,
                             "steps_done": 0, "interventions": 0,
                             "resolved_by": "steps", "judge_cost": 0.0,
                             "judge_score": None, "synthetic": False,
                             "injection": False})
    for r in rows:
        s = m[r["mission"]]
        # One fabricated row makes the whole mission fabricated.
        s["synthetic"] = s["synthetic"] or bool(r.get("synthetic"))
        if r["kind"] == "call":
            s["cost"] += r["cost"]
            s["in"] += r["in"]
            s["cached"] += r["cached"]
            # Rows written before cache writes were tracked have no key.
            s["written"] += r.get("written", 0)
            s["out"] += r["out"]
            s["calls"] += 1
        elif r["kind"] == "judge":
            # Judge spend is real but it is not mission spend. Pooling them
            # would inflate cost per resolved task with the cost of asking.
            s["judge_cost"] += r.get("cost", 0.0)
            s["judge_score"] = r.get("score")
            s["injection"] = s["injection"] or bool(r.get("injection_attempted"))
        else:
            s["resolved"] = r["resolved"]
            s["steps_done"] = r["steps_done"]
            s["interventions"] = r["interventions"]
            s["resolved_by"] = r.get("resolved_by", "steps")

    total_cost = sum(s["cost"] for s in m.values())
    resolved = [k for k, s in m.items() if s["resolved"]]
    total_in = sum(s["in"] for s in m.values())
    total_cached = sum(s["cached"] for s in m.values())
    total_written = sum(s["written"] for s in m.values())
    total_iv = sum(s["interventions"] for s in m.values())
    total_judge = sum(s["judge_cost"] for s in m.values())
    synthetic = [k for k, s in m.items() if s["synthetic"]]
    injected = [k for k, s in m.items() if s["injection"]]
    judged = [k for k, s in m.items() if s["resolved_by"] == "judge"]
    return {
        "missions": dict(m),
        "total_cost": total_cost,
        "task_success_rate": len(resolved) / len(m) if m else 0.0,
        "cost_per_resolved_task":
            total_cost / len(resolved) if resolved else float("inf"),
        "cache_hit_rate": total_cached / total_in if total_in else 0.0,
        "cache_written_tokens": total_written,
        "judge_cost": total_judge,
        "judged_missions": len(judged),
        "synthetic_missions": len(synthetic),
        "injection_missions": sorted(injected),
        "interventions_per_mission": total_iv / len(m) if m else 0.0,
    }


def quadrant(s: dict) -> str:
    """The matrix: spend vs shipped output, split by whether it resolved.

    Both spend levels split on resolved. A mission that moved and did not
    finish is not a win at any price: calling a cheap failure a CHEAP WIN
    is how a failing mission stays in the rotation for months.
    """
    hot = s["cost"] > HOT_SPEND_USD
    shipped = s["steps_done"] > 0
    if hot and not shipped:
        return "LEAK"
    if not hot and shipped:
        return "CHEAP WIN" if s["resolved"] else "CHEAP MISS"
    if hot and shipped:
        return "VELOCITY" if s["resolved"] else "VELOCITY THEATRE"
    return "IDLE"


def _money(x: float) -> str:
    """No resolved task yet means the ratio is undefined, not infinite.
    Printing $inf in a board deck invites the wrong question."""
    return "n/a (no resolved task yet)" if math.isinf(x) else f"${x:.2f}"


def injection_note(a: dict) -> str:
    """An attempt to steer the grader is a security event, not a metric.

    Tool output carries whatever was in the files and commands the agent
    touched, so this is the signal that something in a workspace tried to
    talk to the thing auditing it. It belongs at the top of the report.
    """
    hit = a.get("injection_missions") or []
    if not hit:
        return ""
    return (f"> **The judge reported an instruction attempt in the "
            f"transcript of: {', '.join(hit)}.** Something in those "
            "workspaces tried to steer the grader. Treat those verdicts as "
            "unreliable and read the transcripts before trusting them.")


def synthetic_note(a: dict) -> str:
    """Say plainly when the numbers are fiction, or worse, part fiction.

    A report that silently averages fabricated missions with real ones is
    the one failure mode seeded data can introduce, and it looks exactly
    like a real report.
    """
    fake, total = a["synthetic_missions"], len(a["missions"])
    if not fake:
        return ""
    if fake == total:
        return ("> **Every mission here is fabricated** by `seed_ledger.py`. "
                "These numbers are for exercising the report, not for a "
                "review.")
    real = total - fake
    return (f"> **This ledger mixes {fake} fabricated "
            f"{'mission' if fake == 1 else 'missions'} with {real} real "
            f"{'one' if real == 1 else 'ones'}.** Every number above "
            "averages the two together. Seed into a scratch file and keep "
            "real runs in their own ledger.")


def cache_note(a: dict) -> str:
    """Explain a zero cache hit rate instead of leaving it to be misread.

    Zero reads with zero writes means caching was never switched on, which
    looks identical to a broken prefix in the headline number and is a
    completely different problem.
    """
    if a["cache_hit_rate"] > 0:
        return ""
    if a.get("cache_written_tokens", 0) == 0:
        return ("> **Cache hit rate is 0% because caching is not enabled.** "
                "Nothing was written to cache, so there was nothing to read. "
                "See the Prompt caching section of the README. A prompt "
                "shorter than the model's minimum cacheable prefix also "
                "silently will not cache.")
    return ("> **Cache hit rate is 0% but tokens were written to cache.** "
            "Writes cost 1.25x and are not being read back: the prefix is "
            "changing between calls, or they are more than 5 minutes apart.")


def render(a: dict) -> str:
    lines = ["# FinOps report: task economics", "",
             "| metric | value |", "|---|---|",
             f"| task success rate | {a['task_success_rate']:.0%} |",
             f"| cost per resolved task | {_money(a['cost_per_resolved_task'])} |",
             f"| cache hit rate | {a['cache_hit_rate']:.0%} |",
             f"| interventions per mission | "
             f"{a['interventions_per_mission']:.1f} |",
             f"| total spend | ${a['total_cost']:.2f} |", ""]
    if not a["missions"]:
        lines.append(f"No missions in the ledger yet ({ledger.path()}). "
                     "Run one with `python run.py missions/demo`.")
        return "\n".join(lines)
    for note in (injection_note(a), synthetic_note(a), cache_note(a)):
        if note:
            lines += [note, ""]
    lines += ["| mission | spend | calls | steps | resolved | by | quadrant |",
              "|---|---|---|---|---|---|---|"]
    for k, s in sorted(a["missions"].items()):
        name = f"{k} *(synthetic)*" if s["synthetic"] else k
        by = s["resolved_by"]
        if by == "judge" and s["judge_score"] is not None:
            by = f"judge {s['judge_score']:.2f}"
        lines.append(f"| {name} | ${s['cost']:.2f} | {s['calls']} | "
                     f"{s['steps_done']} | {s['resolved']} | {by} | "
                     f"{quadrant(s)} |")
    if a["judged_missions"]:
        lines += ["", f"Judged {a['judged_missions']} of "
                      f"{len(a['missions'])} missions; grading cost "
                      f"${a['judge_cost']:.2f}, excluded from mission spend "
                      f"above."]
    else:
        lines += ["", "> Every verdict above is the step count proxy: the "
                      "agent said STEP n DONE, which is not the same as "
                      "having done it. Run with `--judge` to grade the "
                      "transcript instead."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="finops.py",
        description="Task economics report from the ledger.")
    p.add_argument("-o", "--output", default=REPORT_PATH, type=pathlib.Path,
                   help=f"where to write the markdown report "
                        f"(default: {REPORT_PATH})")
    p.add_argument("--stdout-only", action="store_true",
                   help="print the report without writing a file")
    args = p.parse_args(argv)

    report = render(analyze(ledger.read()))
    print(report)
    if not args.stdout_only:
        args.output.write_text(report + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
