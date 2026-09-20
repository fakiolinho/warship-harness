"""Score the permission gate against the labelled corpus.

    python evals/run_gate_eval.py          # human readable
    python evals/run_gate_eval.py --json   # for CI or a dashboard

No API key, no network. The number that matters is DENY RECALL: of the
commands that should be blocked, how many are. A miss there is a command
that runs.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from evals.gate_corpus import CORPUS  # noqa: E402
from evals.heldout_corpus import HELD_OUT  # noqa: E402
from harness.gate import decide  # noqa: E402


def score(corpus=None) -> dict:
    rows = []
    for command, wanted, why in (corpus or CORPUS):
        got = decide("run_command", {"command": command})
        rows.append({"command": command, "wanted": wanted, "got": got,
                     "why": why, "ok": got == wanted})

    def recall(label: str) -> tuple[int, int]:
        want = [r for r in rows if r["wanted"] == label]
        return sum(r["ok"] for r in want), len(want)

    deny_hit, deny_n = recall("deny")
    ask_hit, ask_n = recall("ask")
    allow_hit, allow_n = recall("allow")

    # The dangerous failure: should have been blocked, was not.
    escaped = [r for r in rows if r["wanted"] == "deny" and r["got"] != "deny"]
    # The annoying failure: ordinary work refused.
    over = [r for r in rows if r["wanted"] == "allow" and r["got"] != "allow"]

    return {
        "total": len(rows),
        "passed": sum(r["ok"] for r in rows),
        "deny_recall": deny_hit / deny_n if deny_n else 0.0,
        "ask_recall": ask_hit / ask_n if ask_n else 0.0,
        "allow_precision": allow_hit / allow_n if allow_n else 0.0,
        "escaped": escaped,
        "over_blocked": over,
        "rows": rows,
    }


def render(s: dict, title: str = "Gate eval") -> str:
    out = [
        f"# {title}",
        "",
        f"{s['passed']}/{s['total']} cases match the label.",
        "",
        "| metric | value | meaning |",
        "|---|---|---|",
        f"| deny recall | {s['deny_recall']:.0%} | destructive commands actually blocked |",
        f"| ask recall | {s['ask_recall']:.0%} | risky commands actually gated |",
        f"| allow precision | {s['allow_precision']:.0%} | ordinary work not obstructed |",
        "",
    ]
    if s["escaped"]:
        out += [f"## {len(s['escaped'])} destructive commands the gate allows",
                "", "| command | verdict | why it matters |", "|---|---|---|"]
        out += [f"| `{r['command']}` | {r['got']} | {r['why']} |"
                for r in s["escaped"]]
        out += [""]
    if s["over_blocked"]:
        out += [f"## {len(s['over_blocked'])} ordinary commands the gate obstructs",
                "", "| command | verdict |", "|---|---|"]
        out += [f"| `{r['command']}` | {r['got']} |" for r in s["over_blocked"]]
        out += [""]
    if not s["escaped"] and not s["over_blocked"]:
        out += ["Every labelled case matches.", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Score the gate against the corpus.")
    p.add_argument("--json", action="store_true", help="machine readable")
    p.add_argument("--min-deny-recall", type=float, default=0.0,
                   help="exit non-zero below this, to ratchet in CI")
    args = p.parse_args(argv)

    tuned = score(CORPUS)
    held = score(HELD_OUT)
    if args.json:
        print(json.dumps(
            {"tuned": {k: v for k, v in tuned.items() if k != "rows"},
             "held_out": {k: v for k, v in held.items() if k != "rows"}},
            indent=2, default=str))
    else:
        print(render(tuned, "Gate eval (tuned corpus)"))
        print("The gate was written against the corpus above, so this "
              "number is a regression test, not a measurement.\n")
        print(render(held, "Gate eval (held out)"))
        print("This one is the measurement. A gap below the tuned number "
              "is normal and honest; no gap usually means contamination.\n")

    floor_failed = False
    for name, s in (("tuned", tuned), ("held out", held)):
        if s["deny_recall"] < args.min_deny_recall:
            print(f"FAIL: {name} deny recall {s['deny_recall']:.0%} is below "
                  f"the {args.min_deny_recall:.0%} floor", file=sys.stderr)
            floor_failed = True
    return 1 if floor_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
