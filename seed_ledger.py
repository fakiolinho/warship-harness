"""Fabricate a ledger so the FinOps report has volume to exercise.

    python seed_ledger.py --out demo_ledger.jsonl --missions 40
    WARSHIP_LEDGER=demo_ledger.jsonl python finops.py

One real mission produces a report with one row, which tells you nothing
about whether the quadrants, the $1 hot spend line, or the judge columns
actually work. This makes that data without spending anything.

Deterministic: the same seed gives the same ledger, byte for byte. No model
call is involved and none should be. Fabricating plausible numbers is a
generator's job, not a language model's, and a model would cost money to
produce data that is fictional either way.

The output is fiction, and every row says so: each carries "synthetic":
true. The script still refuses to write the default ledger, but the marker
is what makes the honest workflow safe. Point WARSHIP_LEDGER at a seeded
file and run real missions into it, and finops.py will tell you the report
is mixing fabricated rows with real ones instead of quietly averaging them
together.
"""

import argparse
import json
import pathlib
import random
import sys
import time

from harness import ledger

# Shapes worth having in the data, so every branch of the report is covered.
PROFILES = [
    # name,        weight, calls,    cost/call,      resolve rate, interventions
    ("dep-bump", 30, (3, 8), (0.004, 0.02), 0.90, (0, 1)),
    ("repo-health", 25, (2, 5), (0.003, 0.01), 0.95, (0, 0)),
    ("docs-drift", 15, (4, 12), (0.01, 0.06), 0.70, (0, 2)),
    ("flaky-triage", 15, (20, 55), (0.03, 0.12), 0.45, (1, 4)),
    ("schema-migrate", 10, (30, 60), (0.05, 0.20), 0.30, (2, 6)),
    ("log-sweep", 5, (1, 3), (0.001, 0.004), 0.60, (0, 1)),
]


def seed(
    out: pathlib.Path, n: int, rng: random.Random, judge_fraction: float = 0.5
) -> dict:
    names = [p[0] for p in PROFILES]
    weights = [p[1] for p in PROFILES]
    rows, stats = [], {"resolved": 0, "judged": 0, "spend": 0.0}
    now = int(time.time())

    for i in range(n):
        profile = PROFILES[names.index(rng.choices(names, weights)[0])]
        _, _, call_range, cost_range, resolve_rate, iv_range = profile
        mission = f"{profile[0]}-{i:03d}"
        calls = rng.randint(*call_range)
        ts = now - rng.randint(0, 14 * 86_400)

        # Cache reads climb with call count: later turns reuse the prefix.
        for c in range(calls):
            cost = rng.uniform(*cost_range)
            fresh = rng.randint(400, 3_000)
            cached = 0 if c == 0 else int(fresh * rng.uniform(0.3, 0.85))
            written = fresh if c == 0 else 0
            rows.append(
                {
                    "kind": "call",
                    "mission": mission,
                    "model": "sonnet",
                    "in": fresh + cached + written,
                    "out": rng.randint(40, 400),
                    "cached": cached,
                    "written": written,
                    "cost": round(cost, 6),
                    "ts": ts + c * 7,
                    "synthetic": True,
                }
            )
            stats["spend"] += cost

        resolved = rng.random() < resolve_rate
        steps = rng.randint(1, 4) if resolved else rng.randint(0, 2)
        resolved_by = "steps"

        if rng.random() < judge_fraction:
            resolved_by = "judge"
            stats["judged"] += 1
            # A judge is stricter than counting STEP lines: some missions the
            # proxy calls resolved do not survive a look at the transcript.
            if resolved and rng.random() < 0.20:
                resolved = False
            score = rng.uniform(0.75, 1.0) if resolved else rng.uniform(0.1, 0.6)
            rows.append(
                {
                    "kind": "judge",
                    "mission": mission,
                    "model": "sonnet",
                    "rubric": "v1",
                    "resolved": resolved,
                    "score": round(score, 3),
                    "reasoning": "synthetic verdict from seed_ledger.py",
                    "failed_steps": [] if resolved else [rng.randint(1, 3)],
                    "in": rng.randint(800, 4_000),
                    "out": rng.randint(60, 200),
                    "cached": 0,
                    "cost": round(rng.uniform(0.002, 0.01), 6),
                    "ts": ts + calls * 7 + 1,
                    "synthetic": True,
                }
            )

        rows.append(
            {
                "kind": "outcome",
                "mission": mission,
                "resolved": resolved,
                "steps_done": steps,
                "interventions": rng.randint(*iv_range),
                "resolved_by": resolved_by,
                "ts": ts + calls * 7 + 2,
                "synthetic": True,
            }
        )
        stats["resolved"] += int(resolved)

    rows.sort(key=lambda r: r["ts"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    stats["rows"] = len(rows)
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="seed_ledger.py",
        description="Generate a synthetic ledger for exercising finops.py.",
    )
    p.add_argument(
        "-o",
        "--out",
        type=pathlib.Path,
        default=pathlib.Path("demo_ledger.jsonl"),
        help="where to write (default: demo_ledger.jsonl)",
    )
    p.add_argument(
        "-n",
        "--missions",
        type=int,
        default=40,
        help="how many missions to fabricate (default: 40)",
    )
    p.add_argument(
        "--seed", type=int, default=1729, help="RNG seed; same seed gives the same file"
    )
    p.add_argument(
        "--judge-fraction",
        type=float,
        default=0.5,
        help="share of missions graded by a judge (default: 0.5)",
    )
    args = p.parse_args(argv)

    if args.out.name == ledger.DEFAULT_LEDGER or args.out == ledger.path():
        sys.exit(
            f"error: refusing to write {args.out}, which is a real "
            "ledger. Fabricated rows are indistinguishable from real "
            "ones once they are in there. Pick another path."
        )

    stats = seed(args.out, args.missions, random.Random(args.seed), args.judge_fraction)
    print(f"wrote {stats['rows']} rows for {args.missions} missions to {args.out}")
    print(
        f"  {stats['resolved']} resolved, {stats['judged']} judged, "
        f"${stats['spend']:.2f} of fabricated mission spend"
    )
    print(f"\nWARSHIP_LEDGER={args.out} python finops.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
