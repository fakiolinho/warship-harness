"""The docs make checkable claims. Check them.

Every factual claim in a README rots, and the line count in this one had
drifted three times before anyone noticed, because nothing was watching.
A claim a test can verify should be verified by a test, not by whoever
happens to reread the file.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ["README.md", "AGENTS.md", "CLAUDE.md", ".cursor/rules/warship-harness.mdc"]
SOURCE = [
    "harness",
    "agent.py",
    "run.py",
    "finops.py",
    "selfcheck.py",
    "seed_ledger.py",
]


def _source_lines() -> int:
    total = 0
    for name in SOURCE:
        p = ROOT / name
        files = sorted(p.glob("*.py")) if p.is_dir() else [p]
        total += sum(len(f.read_text().splitlines()) for f in files)
    return total


@pytest.mark.parametrize("doc", DOCS)
def test_the_stated_line_count_is_roughly_true(doc):
    """Drifted 600 -> 750 -> 1,200 -> 1,800 without anyone noticing."""
    text = (ROOT / doc).read_text()
    claims = [
        int(m.replace(",", ""))
        for m in re.findall(r"about ([\d,]+) (?:readable )?lines", text)
    ]
    actual = _source_lines()
    for claimed in claims:
        assert abs(claimed - actual) / actual < 0.20, (
            f"{doc} claims ~{claimed:,} lines; the tree has {actual:,}"
        )


# Written by a run, not committed, so a doc may name them before they exist.
RUNTIME_FILES = {
    "pending.md",
    "approved.md",
    "state.json",
    "ledger.jsonl",
    "finops_report.md",
    "demo_ledger.jsonl",
    "mission.md",
}


@pytest.mark.parametrize("doc", DOCS)
def test_every_referenced_path_exists(doc):
    """A doc naming a file that was renamed sends readers nowhere."""
    text = (ROOT / doc).read_text()
    referenced = set(
        re.findall(
            r"`((?:harness|tests|evals|missions)/[\w./-]+"
            r"|[\w-]+\.(?:py|md|toml|txt))`",
            text,
        )
    )
    missing = []
    for ref in referenced:
        if pathlib.Path(ref).name in RUNTIME_FILES:
            continue
        if "/" in ref:
            if not (ROOT / ref).exists():
                missing.append(ref)
        # A bare filename may live in any package; find it anywhere.
        elif not any(ROOT.glob(f"**/{ref}")):
            missing.append(ref)
    assert not missing, f"{doc} references missing paths: {sorted(missing)}"


def test_documented_flags_exist():
    """A flag in the README that argparse does not define is a dead end."""
    import run

    readme = (ROOT / "README.md").read_text()
    flags = set(re.findall(r"python run\.py [^\n`]*?(--[a-z-]+)", readme))
    assert flags, "no run.py flags found in the README; regex drifted?"
    takes_value = {"--model", "--ceiling"}
    for flag in flags:
        argv = ["missions/demo", flag]
        if flag in takes_value:
            argv.append("1.0" if flag == "--ceiling" else "x")
        run.parse_args(argv)  # raises SystemExit on an unknown flag


def test_the_env_vars_the_docs_name_are_the_ones_the_code_reads():
    """.env.example is the contract; drift there is silent."""
    example = (ROOT / ".env.example").read_text()
    documented = set(re.findall(r"^#?\s*(WARSHIP_[A-Z_]+)=", example, re.M))
    source = " ".join(
        (ROOT / f).read_text() for f in ["harness/ledger.py", "harness/gate.py"]
    )
    used = set(re.findall(r'"(WARSHIP_[A-Z_]+)"', source))
    assert used <= documented, f"undocumented env vars: {used - documented}"


def test_the_container_job_exists_in_ci():
    """The docs now claim CI builds the image. If that job is removed the
    claim becomes false silently, which is how the 'never been built'
    problem started."""
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "docker build -t warship-harness" in ci
    assert "/etc/passwd" in ci, "the boundary assertion was dropped"


def test_the_untested_part_of_the_container_setup_is_still_flagged():
    """CI runs the image without host mounts, so -u and the data volume
    are still unexercised. Claiming the whole recipe is verified would be
    the same overclaim in a new place."""
    for doc in ("README.md", "SECURITY.md", "Dockerfile"):
        text = (ROOT / doc).read_text()
        if "docker run" in text:
            assert re.search(
                r"not (?:covered|exercised)|is not, because|"
                r"still unverified|NOT covered",
                text,
            ), f"{doc} shows docker run without flagging the untested mounts"


def test_the_hook_runs_what_ci_runs():
    """A hook that checks less than CI gives false confidence; one that
    checks more gets bypassed. They drift apart silently, so tie them."""
    hook = (ROOT / ".pre-commit-config.yaml").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    for command in (
        "python selfcheck.py",
        "python -m pytest",
        "run_gate_eval.py --min-deny-recall 1.0",
    ):
        stem = command.replace("python -m ", "").replace("python ", "")
        assert stem.split()[0] in hook, f"hook is missing {stem}"
        assert stem.split()[0] in ci, f"ci is missing {stem}"


def test_the_hook_formats_and_lints():
    """Both halves matter: the formatter settles layout so nobody argues
    about it, the linter catches what layout cannot."""
    hook = (ROOT / ".pre-commit-config.yaml").read_text()
    entries = [
        ln.split("entry:", 1)[1].strip() for ln in hook.splitlines() if "entry:" in ln
    ]
    assert entries, "no hook entries found; config shape changed?"
    assert any("ruff format" in e for e in entries)
    assert any("ruff check --fix" in e for e in entries)


def test_ci_asserts_formatting_too():
    """A formatter only in the hook drifts the moment someone commits
    with --no-verify."""
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "ruff format --check" in ci
