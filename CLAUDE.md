# CLAUDE.md

See **[AGENTS.md](AGENTS.md)** for the full orientation: commands, layout,
the invariants that must not be broken, conventions, and gotchas.

Quick version:

```bash
pre-commit install    # hook runs the checks below on every commit
python selfcheck.py   # fast smoke test, no API key
pytest                # full suite, no API key, no network
ruff check .          # lint

python evals/run_gate_eval.py   # does the gate CATCH things (also in CI)
python seed_ledger.py --out demo_ledger.jsonl --missions 40   # data to look at
```

Python 3.10+ required. All three must pass before a pull request.

The load bearing rules, in one line each:

- The permission gate sits outside the model's code path; deny beats ask.
- Volatile text goes *after* the stable prompt prefix, never before it.
- With no TTY, an `ask` verdict is declined — never auto approved.
- Memory goes pending → **a human approves** → loaded. Never auto promote.
- `state.checkpoint()` upserts by step number; it must stay idempotent.
- `finops.py` is deterministic Python; no model call belongs in it. The LLM
  judge runs at *record* time and writes its verdict to the ledger, so the
  report stays pure arithmetic over recorded facts.
- No test may require an API key. Use `ScriptedModel` in `tests/conftest.py`.
- Tests prove wiring; `evals/` proves behaviour. Quote the held out corpus
  number, never the one the rules were tuned against.
- The budget refuses in `wrap_model_call`, before dispatch — not after.
- The gate stops mistakes, not intent: `run_command` is `shell=True` and
  unconfined. The container is the boundary — README, "Why the container".
- Deliberate shortcuts carry a `ponytail:` comment naming the upgrade path.
