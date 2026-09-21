"""Externalized mission state. A crash at step 40 resumes at step 40."""

import json
import os
import pathlib
import tempfile


def state_path(mission_dir: pathlib.Path) -> pathlib.Path:
    return mission_dir / "state.json"


def checkpoint(
    mission_dir: pathlib.Path,
    step_no: int,
    summary: str,
    artifacts: list[str] | None = None,
) -> None:
    """Record step `step_no` as done. Idempotent: re-recording a step
    number overwrites it instead of appending a duplicate.

    The agent can restate a STEP line (a retry, a resumed run, a stream
    that replays the message). Appending blindly would inflate steps_done
    in the ledger, and every inflated step lands in the next resume prompt.
    """
    p = state_path(mission_dir)
    state = {"steps": read_steps(mission_dir)}
    entry = {"n": step_no, "done": summary, "artifacts": artifacts or []}
    steps = [s for s in state["steps"] if s.get("n") != step_no]
    steps.append(entry)
    state["steps"] = sorted(steps, key=lambda s: s["n"])
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, json.dumps(state, indent=2, sort_keys=True))


def _atomic_write(path: pathlib.Path, text: str) -> None:
    """Write via a temp file and rename, so no reader sees a half file.

    write_text() truncates and then writes. Another process reading the
    mission in that window gets an empty or partial file and a
    JSONDecodeError. os.replace is atomic on POSIX, so a reader sees
    either the old state or the new one, never a torn one.

    ponytail: this stops corruption, not lost updates. Two runs of the
    same mission still overwrite each other's checkpoints. Upgrade path:
    a lock file, or one mission directory per run.
    """
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


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
    return (
        brief
        + "\n\nALREADY COMPLETED, do not redo:\n"
        + done
        + "\nContinue from the next step."
    )


def read_steps(mission_dir: pathlib.Path) -> list[dict]:
    p = state_path(mission_dir)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text()).get("steps", [])
    except (json.JSONDecodeError, OSError):
        # A state file written by an older, non atomic version can still
        # be torn. Losing progress beats refusing to run the mission.
        return []
