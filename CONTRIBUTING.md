# Contributing

Thanks for looking. This project is small on purpose: it is a reference
harness, not a framework. The bar for new code is that it earns its place.

## Setup

Python 3.10 or newer is required (LangChain 1.x does not support 3.9).

```bash
git clone git@github.com:fakiolinho/warship-harness.git
cd warship-harness

python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

## The loop

Install the hook once and it runs these for you on every commit:

```bash
pre-commit install
```

Or run them by hand:

```bash
python selfcheck.py     # fast smoke test, no API key, no pytest
pytest                  # full suite, no API key, no network
ruff check .            # lint
```

The hook runs the same checks CI runs, so a commit that passes locally
passes there. It takes a few seconds. `git commit --no-verify` skips it
when you want to record work in progress.

There is deliberately no `ruff format`. The comments here are wrapped by
hand so the reasoning lines up with the code it explains, and the
formatter reflows about 1,800 lines of that. Lint autofix is safe; a
reformat is not.

All three must pass before you open a pull request. CI runs exactly these
on Python 3.10 through 3.13, so a green local run means a green CI run.

Nothing in the test suite calls a model API. The suite drives the real
`create_agent` graph with a scripted model (`tests/conftest.py`), which is
what lets CI prove the middleware wiring on every push. Keep it that way:
a test that needs `ANTHROPIC_API_KEY` cannot run in CI and will be asked to
be rewritten.

## What a good change looks like

**Every behavior change needs a test.** Not a test that restates the code,
a test that would fail if the behavior regressed. The existing tests are
named after the property they protect, not the function they call. Follow
that.

**Keep the simplifications honest.** Deliberate shortcuts carry a
`ponytail:` comment naming the ceiling and the upgrade path:

```python
# ponytail: subprocess in cwd stands in for a real sandbox.
# Upgrade path: Docker / firejail with a network allowlist.
```

If you add a shortcut, label it the same way. If you remove one, remove
its comment. An unlabeled shortcut is how a prototype quietly ships.

**Controls are not decorations.** The gate, the budget ceiling, and the
memory review step exist to say no. A change that makes one of them easier
to bypass needs to argue for itself in the pull request description.

**Match the surrounding prose.** Comments here explain *why*, and the
README is written to be read start to finish. Please keep the register.

## What is likely to be accepted

- Upgrade paths for the `ponytail:` shortcuts, behind a flag or a subclass
- New gate rules, with a test per rule
- New example missions under `missions/`
- Adapters for other model providers, as long as the ledger still records
  tokens and cost
- Documentation that removes a step someone would otherwise get wrong

## What is likely to be declined

- A plugin system, a config framework, or a class hierarchy. The value of
  this repo is that you can read all of it in one sitting.
- Auto-approving memory. The human review step is the feature.
- Vendored dependencies or a lockfile for an application that is meant to
  be copied into other projects.

## Reporting bugs

Open an issue with the output of `python selfcheck.py`, your Python
version, and `pip freeze | grep langchain`. If a mission misbehaved,
`ledger.jsonl` and the mission's `state.json` are the two files worth
attaching. Scrub them first: they can contain paths and command output
from your workspace.

## Security

Do not open a public issue for a security problem. See [SECURITY.md](SECURITY.md).
