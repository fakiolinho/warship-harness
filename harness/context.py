"""Bounded tool output: cap what enters the context, persist the rest to disk."""

import hashlib
import pathlib

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

# Roughly 2K tokens. ponytail: characters, not tokens. Upgrade path: a
# real tokenizer count, if context limits ever get tight.
MAX_INLINE_CHARS = 8_000


def bounded(text: str, artifact_dir: pathlib.Path) -> str:
    """Pure function: return text unchanged, or persist it and return a stub."""
    if len(text) <= MAX_INLINE_CHARS:
        return text
    artifact_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(text.encode()).hexdigest()[:12] + ".txt"
    path = artifact_dir / name
    path.write_text(text)
    return (
        f"[output was {len(text)} chars; full text saved to {path}]\n"
        f"First lines:\n{text[:800]}"
    )


class BoundedToolOutput(AgentMiddleware):
    def __init__(self, artifact_dir: pathlib.Path):
        super().__init__()
        self.artifact_dir = artifact_dir

    def wrap_tool_call(self, request, handler):
        result = handler(request)
        if isinstance(result, ToolMessage) and isinstance(result.content, str):
            result.content = bounded(result.content, self.artifact_dir)
        return result
