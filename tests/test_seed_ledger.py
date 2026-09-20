"""The generator must be reproducible and must not touch a real ledger."""
import random

import pytest

import finops
import seed_ledger
from harness import ledger


def _seed(tmp_path, n=25, s=1729, judge_fraction=0.5):
    out = tmp_path / "demo.jsonl"
    stats = seed_ledger.seed(out, n, random.Random(s), judge_fraction)
    return out, stats


def test_the_same_seed_gives_the_same_file(tmp_path):
    """Fabricated data you cannot reproduce is not data, it is noise."""
    a, _ = _seed(tmp_path / "a")
    b, _ = _seed(tmp_path / "b")
    assert a.read_text() == b.read_text()


def test_a_different_seed_gives_a_different_file(tmp_path):
    a, _ = _seed(tmp_path / "a", s=1)
    b, _ = _seed(tmp_path / "b", s=2)
    assert a.read_text() != b.read_text()


def test_the_output_parses_as_a_ledger(tmp_path, monkeypatch):
    out, stats = _seed(tmp_path)
    monkeypatch.setenv("WARSHIP_LEDGER", str(out))
    rows = ledger.read()
    assert len(rows) == stats["rows"]
    assert {r["kind"] for r in rows} <= {"call", "judge", "outcome"}


def test_the_report_renders_from_it(tmp_path, monkeypatch):
    out, _ = _seed(tmp_path)
    monkeypatch.setenv("WARSHIP_LEDGER", str(out))
    a = finops.analyze(ledger.read())
    assert len(a["missions"]) == 25
    assert 0 < a["task_success_rate"] < 1       # both outcomes represented
    assert a["total_cost"] > 0


def test_it_produces_every_quadrant(tmp_path, monkeypatch):
    """The point of volume: exercise branches one real mission cannot."""
    out, _ = _seed(tmp_path, n=200)
    monkeypatch.setenv("WARSHIP_LEDGER", str(out))
    a = finops.analyze(ledger.read())
    seen = {finops.quadrant(s) for s in a["missions"].values()}
    assert {"CHEAP WIN", "VELOCITY", "VELOCITY THEATRE"} <= seen


def test_it_produces_both_verdict_sources(tmp_path, monkeypatch):
    out, _ = _seed(tmp_path, n=60)
    monkeypatch.setenv("WARSHIP_LEDGER", str(out))
    a = finops.analyze(ledger.read())
    sources = {s["resolved_by"] for s in a["missions"].values()}
    assert sources == {"steps", "judge"}


def test_judge_fraction_zero_produces_no_judge_rows(tmp_path, monkeypatch):
    out, _ = _seed(tmp_path, judge_fraction=0.0)
    monkeypatch.setenv("WARSHIP_LEDGER", str(out))
    assert finops.analyze(ledger.read())["judged_missions"] == 0


def test_cache_reads_only_appear_after_the_first_call(tmp_path, monkeypatch):
    """The first call of a mission has nothing to read back."""
    out, _ = _seed(tmp_path)
    monkeypatch.setenv("WARSHIP_LEDGER", str(out))
    first = {}
    for r in ledger.read():
        if r["kind"] == "call" and r["mission"] not in first:
            first[r["mission"]] = r
    assert all(r["cached"] == 0 for r in first.values())


def test_it_refuses_to_write_the_default_ledger(tmp_path, monkeypatch):
    """Fabricated rows in a real ledger are indistinguishable from real
    ones the moment you look away."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        seed_ledger.main(["--out", ledger.DEFAULT_LEDGER])
    assert "refusing" in str(e.value)
    assert not (tmp_path / ledger.DEFAULT_LEDGER).exists()


def test_it_refuses_the_configured_ledger_too(tmp_path, monkeypatch):
    real = tmp_path / "prod.jsonl"
    monkeypatch.setenv("WARSHIP_LEDGER", str(real))
    with pytest.raises(SystemExit):
        seed_ledger.main(["--out", str(real)])
    assert not real.exists()
