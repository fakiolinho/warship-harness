"""The memory loop: a human sits between pending and approved."""
import pytest

from harness import memory


def test_nothing_approved_means_nothing_loaded(tmp_path):
    assert memory.load(tmp_path / "memory") == ""


def test_pending_is_not_loaded_until_approved(tmp_path):
    mem = tmp_path / "memory"
    memory.submit_for_review("- ci is flaky", mem)
    assert memory.load(mem) == ""        # the whole point of the gate
    memory.approve(mem)
    assert "ci is flaky" in memory.load(mem)


def test_approving_clears_the_pending_file(tmp_path):
    mem = tmp_path / "memory"
    memory.submit_for_review("- a fact", mem)
    memory.approve(mem)
    assert not memory.pending_path(mem).exists()


def test_approvals_accumulate(tmp_path):
    mem = tmp_path / "memory"
    memory.submit_for_review("- first fact", mem)
    memory.approve(mem)
    memory.submit_for_review("- second fact", mem)
    memory.approve(mem)
    loaded = memory.load(mem)
    assert "first fact" in loaded and "second fact" in loaded


def test_rejecting_drops_the_batch(tmp_path):
    mem = tmp_path / "memory"
    memory.submit_for_review("- a wrong fact", mem)
    memory.reject(mem)
    assert memory.load(mem) == ""
    assert not memory.pending_path(mem).exists()


def test_approving_nothing_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match="nothing to approve"):
        memory.approve(tmp_path / "memory")


def test_distill_uses_the_injected_model(tmp_path):
    class FakeModel:
        def invoke(self, prompt):
            self.prompt = prompt
            return type("R", (), {"content": "- distilled fact"})()
    m = FakeModel()
    assert memory.distill("some logs", m) == "- distilled fact"
    assert "some logs" in m.prompt
