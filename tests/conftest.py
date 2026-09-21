"""Shared fixtures.

The point of the scripted model: the whole harness (gate, bounded output,
budget, checkpointing, ledger) can be exercised end to end with no API key
and no network, so CI proves the wiring on every push.
"""

import pathlib
import sys

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

USAGE = {
    "input_tokens": 1000,
    "output_tokens": 50,
    "total_tokens": 1050,
    "input_token_details": {"cache_read": 800},
}


class ScriptedModel(BaseChatModel):
    """A chat model that replays a fixed list of AIMessages.

    LangChain's own fakes do not implement bind_tools, which create_agent
    requires, so the agent graph cannot run against them.
    """

    script: list = []
    calls: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        i = len(self.calls)
        self.calls.append(messages)
        msg = self.script[min(i, len(self.script) - 1)]
        return ChatResult(generations=[ChatGeneration(message=msg)])


def ai(content: str, tool_calls=None, usage=USAGE) -> AIMessage:
    return AIMessage(content=content, tool_calls=tool_calls or [], usage_metadata=usage)


def call(name: str, args: dict, id: str = "c1") -> dict:
    return {"name": name, "args": args, "id": id, "type": "tool_call"}


@pytest.fixture
def isolated_ledger(tmp_path, monkeypatch):
    """Point the ledger at tmp_path so tests never touch the repo's ledger."""
    p = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("WARSHIP_LEDGER", str(p))
    return p


@pytest.fixture
def mission(tmp_path):
    """A mission directory with a three step brief."""
    d = tmp_path / "missions" / "demo"
    d.mkdir(parents=True)
    (d / "mission.md").write_text(
        "# Mission: test\n\n"
        "1. First thing.\n"
        "2. Second thing.\n"
        "3. Third thing.\n\n"
        "State STEP <n> DONE: <summary> after each step.\n"
    )
    return d
