# AGENTS.md

Orientation for AI coding assistants (Cursor, Claude Code, Codex, Copilot,
Windsurf, Aider) and for humans arriving cold. Read this before editing.

`.cursor/rules/warship-harness.mdc` and `CLAUDE.md` point here. This file is
the single source of truth; do not let the pointers drift.

## What this project is

A reference **agent harness**: the code that wraps a language model to make
it safe and affordable to run unattended. The thesis is `agent = model +
harness`. The model supplies reasoning. Everything in `harness/` supplies
the rest.

It is **not** a framework. It is about 750 lines meant to be read in one sitting
and copied into other projects. Optimize for legibility, not extensibility.

## Commands

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python selfcheck.py   # fast smoke test: no pytest, no API key
pytest                # full suite: no API key, no network
ruff check .          # lint

python run.py missions/demo          # a real mission; needs ANTHROPIC_API_KEY
python run.py missions/demo --ceiling 1.00
python finops.py                     # task economics report
```

Python **3.10+** is required; LangChain 1.x dropped 3.9. macOS system Python
is 3.9, so always create the venv from an explicit `python3.12`.

## Layout

| Path | Responsibility |
|---|---|
| `harness/gate.py` | allow / ask / deny on every tool call. Deny wins. |
| `harness/context.py` | cap tool output entering context, spill the rest to disk |
| `harness/budget.py` | per-mission cost ceiling; pauses instead of burning |
| `harness/state.py` | checkpoint + resume; a crash at step 40 resumes at 40 |
| `harness/memory.py` | distill → pending → **human approves** → loaded |
| `harness/ledger.py` | every model call and mission outcome, as JSONL |
| `finops.py` | deterministic task economics report from the ledger |
| `agent.py` | wires the stack onto `create_agent`, plus two demo tools |
| `run.py` | mission entrypoint: stream, checkpoint, record outcome |
| `selfcheck.py` | assert-based smoke test of every component |
| `tests/` | pytest suite, including end-to-end via a scripted model |

## Invariants — do not break these

These are the reasons the project exists. A change that violates one needs
to argue for itself explicitly, not slip through.

1. **The gate sits outside the model's code path.** The model never decides
   whether it is allowed to do something. `decide()` stays a pure function
   so it can be tested and audited on its own. Deny always beats ask.

2. **The cacheable prefix must not drift.** In `state.resume_prompt()` and
   in `build_agent()`'s system prompt, volatile text (progress, approved
   memory) goes *after* the stable text. Cache hit rate is the dominant
   cost lever; a byte of churn at the front invalidates the whole prefix.
   `tests/test_agent_e2e.py` asserts this — do not "tidy" it away.
   Ordering alone caches nothing: Anthropic needs a `cache_control`
   breakpoint, which `agent.default_model()` sets. Both halves are load
   bearing, and `tests/test_caching.py` guards the breakpoint.

3. **Every control must be able to say no.** The budget ceiling raises
   `MissionPaused`. The gate returns an error `ToolMessage`. With no TTY,
   an `ask` verdict is **declined**, never auto-approved. Unattended runs
   must not approve themselves.

4. **Memory is human-reviewed.** `pending.md` → a person reads it →
   `approved.md`. Never auto-promote. Approved memory lands in the system
   prompt of every later mission; it is a durable injection surface.

5. **Checkpointing is idempotent.** `state.checkpoint()` upserts by step
   number. A restated `STEP n DONE` line must not inflate `steps_done`,
   because that number feeds the FinOps report.

6. **FinOps math is deterministic Python.** No model call in `finops.py`.
   Math that goes in front of a board should not hallucinate. The LLM judge
   does not break this: it runs at *record* time and writes a verdict into
   the ledger with its model and rubric version, so the report is still pure
   arithmetic over recorded facts and re-running it on the same ledger gives
   the same numbers. A judge called from inside the report would break it.

7. **The test suite never calls a model API.** `tests/conftest.py` has a
   `ScriptedModel` that implements `bind_tools`, which is what lets the
   real `create_agent` graph run offline. A test needing `ANTHROPIC_API_KEY`
   cannot run in CI. Write it against the scripted model instead.

## Conventions

**`ponytail:` comments mark deliberate shortcuts.** Each names its ceiling
and its upgrade path:

```python
# ponytail: subprocess in cwd stands in for a real sandbox.
# Upgrade path: Docker / firejail with a network allowlist.
```

Adding a shortcut means adding one of these. Removing the shortcut means
removing the comment. An unlabeled shortcut is how a prototype quietly
ships to production.

**Comments explain why, not what.** The code says what. Existing comments
give the reasoning behind a control or name the failure it prevents. Match
that register; do not add narration.

**Test names state the property, not the function.** `test_deny_beats_ask`,
not `test_decide_3`. A reader should learn the invariant from the name.

**Prose style.** The README and docs are written to be read start to
finish, in plain declarative sentences. Keep it.

## Gotchas

- `msg.text` on a LangChain message is a `TextAccessor`, not a `str`.
  `run.py` wraps it in `str()`. Do not call it as `.text()` — deprecated.
- `SummarizationMiddleware` needs a real model, so `build_agent` skips it
  when a non-string model is injected. That is why tests pass
  `compaction_model=None`.
- The ledger path is resolved per call via `WARSHIP_LEDGER`, not captured
  at import. Tests rely on this to stay out of the repo's own ledger.
- `agent.WORKSPACE` is a module-level global set by `run.py`. Tools are
  confined to it. Tests call `set_workspace()` directly.
- `harness/` shadows nothing, but `agent.py` and `run.py` are top-level
  modules, not a package. `pyproject.toml` sets `pythonpath = [".", "tests"]`
  so pytest can import them.

## Before you open a pull request

`python selfcheck.py`, `pytest`, and `ruff check .` all pass. CI runs
exactly these across Python 3.10–3.13. See [CONTRIBUTING.md](CONTRIBUTING.md).
