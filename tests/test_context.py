"""Bounded tool output: context is a budget, not a bucket."""
from langchain_core.messages import ToolMessage

from harness.context import MAX_INLINE_CHARS, BoundedToolOutput, bounded


def test_small_output_passes_through(tmp_path):
    assert bounded("small", tmp_path) == "small"
    assert list(tmp_path.glob("*.txt")) == []


def test_output_at_the_limit_is_untouched(tmp_path):
    text = "x" * MAX_INLINE_CHARS
    assert bounded(text, tmp_path) == text


def test_oversized_output_is_persisted_and_stubbed(tmp_path):
    text = "x" * (MAX_INLINE_CHARS + 1)
    stub = bounded(text, tmp_path)
    assert len(stub) < MAX_INLINE_CHARS
    assert "saved to" in stub
    saved = list(tmp_path.glob("*.txt"))
    assert len(saved) == 1
    assert saved[0].read_text() == text     # nothing is lost, only moved


def test_identical_output_is_stored_once(tmp_path):
    text = "y" * (MAX_INLINE_CHARS + 1)
    bounded(text, tmp_path)
    bounded(text, tmp_path)
    assert len(list(tmp_path.glob("*.txt"))) == 1   # content addressed


def test_middleware_truncates_the_tool_message(tmp_path):
    mw = BoundedToolOutput(tmp_path)
    big = "z" * (MAX_INLINE_CHARS + 1)
    out = mw.wrap_tool_call(
        object(), lambda r: ToolMessage(content=big, tool_call_id="c1"))
    assert len(out.content) < MAX_INLINE_CHARS
    assert list(tmp_path.glob("*.txt"))
