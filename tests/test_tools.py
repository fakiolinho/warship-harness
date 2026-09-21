"""The two demo tools. The brief says "stay in the workspace"; these enforce it."""

import agent as agent_module
from agent import read_file, run_command


def test_reads_a_file_inside_the_workspace(tmp_path):
    agent_module.set_workspace(tmp_path)
    (tmp_path / "notes.md").write_text("hello")
    assert read_file.invoke({"path": str(tmp_path / "notes.md")}) == "hello"


def test_refuses_a_path_outside_the_workspace(tmp_path):
    """Telling the model to stay put is not the same as making it."""
    agent_module.set_workspace(tmp_path / "work")
    (tmp_path / "work").mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("SW5-CONTENTS-MUST-NOT-LEAK")
    out = read_file.invoke({"path": str(secret)})
    assert out.startswith("BLOCKED")
    assert "SW5-CONTENTS-MUST-NOT-LEAK" not in out


def test_refuses_traversal_out_of_the_workspace(tmp_path):
    agent_module.set_workspace(tmp_path / "work")
    (tmp_path / "work").mkdir()
    assert read_file.invoke({"path": str(tmp_path / "work" / ".." / "etc")}).startswith(
        "BLOCKED"
    )


def test_a_missing_file_is_an_error_string_not_a_crash(tmp_path):
    agent_module.set_workspace(tmp_path)
    out = read_file.invoke({"path": str(tmp_path / "nope.md")})
    assert out.startswith("ERROR reading")


def test_run_command_returns_stdout(tmp_path):
    agent_module.set_workspace(tmp_path)
    assert "hi" in run_command.invoke({"command": "echo hi"})


def test_run_command_runs_in_the_workspace(tmp_path):
    agent_module.set_workspace(tmp_path)
    (tmp_path / "marker.txt").write_text("x")
    assert "marker.txt" in run_command.invoke({"command": "ls"})


def test_silent_success_still_reports_something(tmp_path):
    agent_module.set_workspace(tmp_path)
    assert "exit 0" in run_command.invoke({"command": "true"})


def test_a_hung_command_costs_one_tool_call_not_the_mission(tmp_path, monkeypatch):
    agent_module.set_workspace(tmp_path)
    monkeypatch.setattr(agent_module, "COMMAND_TIMEOUT_S", 1)
    out = run_command.invoke({"command": "sleep 5"})
    assert out.startswith("ERROR: command timed out")
