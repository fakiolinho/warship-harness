"""Task economics ledger: every model call and every mission outcome, on disk.

Tokens are inputs. Resolved tasks are outputs. This file connects the two
columns so finops.py can report cost per resolved task, not just spend.

The path is `ledger.jsonl` in the working directory. Override it with
WARSHIP_LEDGER to keep one ledger across hosts, or to point runs at a
shared volume. It is resolved per call, so tests and CI can redirect it.
"""

import json
import os
import pathlib
import time

DEFAULT_LEDGER = "ledger.jsonl"


def path() -> pathlib.Path:
    """The ledger file for this process, resolved fresh on every call."""
    return pathlib.Path(os.environ.get("WARSHIP_LEDGER", DEFAULT_LEDGER))


def _append(row: dict) -> None:
    row["ts"] = round(time.time())
    p = path()
    if p.parent != pathlib.Path("."):
        p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def record_call(mission: str, model: str, usage: dict, cost_usd: float) -> None:
    details = usage.get("input_token_details") or {}
    _append(
        {
            "kind": "call",
            "mission": mission,
            "model": model,
            "in": usage.get("input_tokens", 0),
            "out": usage.get("output_tokens", 0),
            "cached": details.get("cache_read") or 0,
            # Writes are input you paid 1.25x for. Recorded separately so the
            # report can tell "not caching" from "caching and never reading".
            "written": details.get("cache_creation") or 0,
            "cost": round(cost_usd, 6),
        }
    )


def record_outcome(
    mission: str,
    resolved: bool,
    steps_done: int,
    interventions: int,
    resolved_by: str = "steps",
) -> None:
    """resolved_by says what decided it: "steps" (the step count proxy) or
    "judge" (an LLM graded the transcript). Recorded because the two are
    different measurements and must not be silently pooled."""
    _append(
        {
            "kind": "outcome",
            "mission": mission,
            "resolved": resolved,
            "steps_done": steps_done,
            "interventions": interventions,
            "resolved_by": resolved_by,
        }
    )


def record_judgement(mission: str, verdict, usage: dict, cost_usd: float) -> None:
    """A judge's verdict, with what produced it and what it cost.

    Kept as its own row kind: judge spend is real money but it is not
    mission spend, so pooling them would corrupt cost per resolved task.
    """
    details = usage.get("input_token_details") or {}
    _append(
        {
            "kind": "judge",
            "mission": mission,
            "model": verdict.model,
            "rubric": verdict.rubric,
            "resolved": verdict.resolved,
            "score": verdict.score,
            "reasoning": verdict.reasoning,
            "failed_steps": verdict.failed_steps,
            "injection_attempted": verdict.injection_attempted,
            "in": usage.get("input_tokens", 0),
            "out": usage.get("output_tokens", 0),
            "cached": details.get("cache_read") or 0,
            "cost": round(cost_usd, 6),
        }
    )


def read() -> list[dict]:
    """Every row, oldest first. Malformed lines are skipped, not fatal:
    a half written row from a killed process must not blind the report."""
    p = path()
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows
