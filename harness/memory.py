"""Log-to-memory loop: distill run logs into facts the next mission loads.

Human review sits between pending and approved. Auto-apply is for prototypes.
"""
import pathlib

DISTILL_PROMPT = """Read these mission logs. Extract only durable facts:
codebase layout, flaky tests, vendor quirks, commands that failed and why.
Output as bullet points. No narration."""


def distill(logs: str, cheap_model) -> str:
    """cheap_model: any LangChain chat model; use the cheapest tier."""
    return cheap_model.invoke(DISTILL_PROMPT + "\n\n" + logs).content


def pending_path(memory_dir: pathlib.Path) -> pathlib.Path:
    return memory_dir / "pending.md"


def approved_path(memory_dir: pathlib.Path) -> pathlib.Path:
    return memory_dir / "approved.md"


def submit_for_review(facts: str, memory_dir: pathlib.Path) -> pathlib.Path:
    memory_dir.mkdir(parents=True, exist_ok=True)
    pending = pending_path(memory_dir)
    pending.write_text(facts)
    return pending


def approve(memory_dir: pathlib.Path) -> pathlib.Path:
    """Human ran this after reading pending.md. Appends to approved.md.

    Nothing pending is a mistake worth naming, not a traceback: it usually
    means the reviewer approved the same batch twice.
    """
    pending = pending_path(memory_dir)
    if not pending.exists():
        raise FileNotFoundError(
            f"nothing to approve: {pending} does not exist. "
            "Run a mission first, or check that it was not already approved.")
    approved = approved_path(memory_dir)
    old = approved.read_text() if approved.exists() else ""
    approved.write_text(old + "\n" + pending.read_text())
    pending.unlink()
    return approved


def reject(memory_dir: pathlib.Path) -> None:
    """Human read pending.md and said no. Drops it without merging."""
    pending = pending_path(memory_dir)
    if pending.exists():
        pending.unlink()


def load(memory_dir: pathlib.Path) -> str:
    approved = approved_path(memory_dir)
    return approved.read_text() if approved.exists() else ""
