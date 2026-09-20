"""Externalized mission state. A crash at step 40 resumes at step 40."""
import json
import pathlib


def state_path(mission_dir: pathlib.Path) -> pathlib.Path:
    return mission_dir / "state.json"


def checkpoint(mission_dir: pathlib.Path, step_no: int, summary: str,
               artifacts: list[str] | None = None) -> None:
    """Record step `step_no` as done. Idempotent: re-recording a step
    number overwrites it instead of appending a duplicate.

    The agent can restate a STEP line (a retry, a resumed run, a stream
    that replays the message). Appending blindly would inflate steps_done
    in the ledger, and every inflated step lands in the next resume prompt.
    """
    p = state_path(mission_dir)
    state = json.loads(p.read_text()) if p.exists() else {"steps": []}
    entry = {"n": step_no, "done": summary, "artifacts": artifacts or []}
    steps = [s for s in state["steps"] if s.get("n") != step_no]
    steps.append(entry)
    state["steps"] = sorted(steps, key=lambda s: s["n"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True))


def resume_prompt(mission_dir: pathlib.Path) -> str:
    """Mission brief, plus what is already done so nothing gets redone.

    Volatile progress goes AFTER the stable brief so the cacheable
    prefix stays byte identical across runs.
    """
    brief = (mission_dir / "mission.md").read_text()
    steps = read_steps(mission_dir)
    if not steps:
        return brief
    done = "\n".join(f"step {s['n']}: {s['done']}" for s in steps)
    return (brief + "\n\nALREADY COMPLETED, do not redo:\n" + done
            + "\nContinue from the next step.")


def read_steps(mission_dir: pathlib.Path) -> list[dict]:
    p = state_path(mission_dir)
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("steps", [])
