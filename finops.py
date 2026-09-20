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
    m = defaultdict(lambda: {"cost": 0.0, "in": 0, "cached": 0, "out": 0,
                             "calls": 0, "resolved": None,
                             "steps_done": 0, "interventions": 0})
    for r in rows:
        s = m[r["mission"]]
        if r["kind"] == "call":
            s["cost"] += r["cost"]
            s["in"] += r["in"]
            s["cached"] += r["cached"]
            s["out"] += r["out"]
            s["calls"] += 1
        else:
            s["resolved"] = r["resolved"]
            s["steps_done"] = r["steps_done"]
            s["interventions"] = r["interventions"]

    total_cost = sum(s["cost"] for s in m.values())
    resolved = [k for k, s in m.items() if s["resolved"]]
    total_in = sum(s["in"] for s in m.values())
    total_cached = sum(s["cached"] for s in m.values())
    total_iv = sum(s["interventions"] for s in m.values())
    return {
        "missions": dict(m),
        "total_cost": total_cost,
        "task_success_rate": len(resolved) / len(m) if m else 0.0,
        "cost_per_resolved_task":
            total_cost / len(resolved) if resolved else float("inf"),
        "cache_hit_rate": total_cached / total_in if total_in else 0.0,
        "interventions_per_mission": total_iv / len(m) if m else 0.0,
    }


def quadrant(s: dict) -> str:
    """The matrix: spend vs shipped output."""
    hot = s["cost"] > HOT_SPEND_USD
    shipped = s["steps_done"] > 0
    if hot and not shipped:
        return "LEAK"
    if not hot and shipped:
        return "CHEAP WIN"
    if hot and shipped:
        return "VELOCITY" if s["resolved"] else "VELOCITY THEATRE"
    return "IDLE"


def _money(x: float) -> str:
    """No resolved task yet means the ratio is undefined, not infinite.
    Printing $inf in a board deck invites the wrong question."""
    return "n/a (no resolved task yet)" if math.isinf(x) else f"${x:.2f}"


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
    lines += ["| mission | spend | calls | steps | resolved | quadrant |",
              "|---|---|---|---|---|---|"]
    for k, s in sorted(a["missions"].items()):
        lines.append(f"| {k} | ${s['cost']:.2f} | {s['calls']} | "
                     f"{s['steps_done']} | {s['resolved']} | {quadrant(s)} |")
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
