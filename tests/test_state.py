"""Checkpoint and resume: a retry pays for one step, not forty."""
from harness import state


def test_no_state_means_the_brief_alone(mission):
    assert state.resume_prompt(mission) == (mission / "mission.md").read_text()
    assert state.read_steps(mission) == []


def test_resume_puts_progress_after_the_stable_brief(mission):
    """Volatile text before the brief would break the cached prefix."""
    brief = (mission / "mission.md").read_text()
    state.checkpoint(mission, 1, "listed files", [])
    resumed = state.resume_prompt(mission)
    assert resumed.startswith(brief)
    assert "step 1: listed files" in resumed
    assert "do not redo" in resumed


def test_recording_a_step_twice_does_not_duplicate_it(mission):
    """A restated STEP line must not inflate steps_done in the ledger."""
    state.checkpoint(mission, 1, "listed files", [])
    state.checkpoint(mission, 1, "listed files", [])
    assert len(state.read_steps(mission)) == 1
    assert state.resume_prompt(mission).count("step 1:") == 1


def test_restating_a_step_keeps_the_latest_summary(mission):
    state.checkpoint(mission, 1, "first attempt", [])
    state.checkpoint(mission, 1, "second attempt", [])
    assert state.read_steps(mission)[0]["done"] == "second attempt"


def test_steps_are_ordered_even_when_recorded_out_of_order(mission):
    state.checkpoint(mission, 3, "third", [])
    state.checkpoint(mission, 1, "first", [])
    assert [s["n"] for s in state.read_steps(mission)] == [1, 3]


def test_artifacts_default_to_empty(mission):
    state.checkpoint(mission, 1, "done")
    assert state.read_steps(mission)[0]["artifacts"] == []


def test_state_survives_a_reread(mission):
    state.checkpoint(mission, 1, "one", ["a.txt"])
    state.checkpoint(mission, 2, "two", [])
    assert [s["done"] for s in state.read_steps(mission)] == ["one", "two"]
    assert state.read_steps(mission)[0]["artifacts"] == ["a.txt"]


def test_concurrent_checkpoints_never_tear_the_file(mission):
    """write_text truncates then writes. A reader in that window got a
    JSONDecodeError, and the README recommends running under cron."""
    import json
    import threading

    errors = []

    def writer(n):
        try:
            for i in range(40):
                state.checkpoint(mission, n * 100 + i, f"step {i}")
        except Exception as why:        # noqa: BLE001 - recorded, asserted
            errors.append(why)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    json.loads(state.state_path(mission).read_text())   # never torn
    assert state.read_steps(mission)                    # and not empty


def test_no_temp_files_are_left_behind(mission):
    state.checkpoint(mission, 1, "one")
    assert list(mission.glob("*.tmp")) == []


def test_a_corrupt_state_file_does_not_block_the_mission(mission):
    """A file written by an older non-atomic version can still be torn.
    Losing progress beats refusing to run."""
    state.checkpoint(mission, 1, "one")
    state.state_path(mission).write_text('{"steps": [{"n": 1,')
    assert state.read_steps(mission) == []
    assert state.resume_prompt(mission) == (mission / "mission.md").read_text()
