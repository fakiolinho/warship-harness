# CLAUDE.md

See **[AGENTS.md](AGENTS.md)** for the full orientation: commands, layout,
the invariants that must not be broken, conventions, and gotchas.

Quick version:

```bash
python selfcheck.py   # fast smoke test, no API key
pytest                # full suite, no API key, no network
ruff check .          # lint

python seed_ledger.py --out demo_ledger.jsonl --missions 40   # data to look at
```

Python 3.10+ required. All three must pass before a pull request.

The load-bearing rules, in one line each:

- The permission gate sits outside the model's code path; deny beats ask.
- Volatile text goes *after* the stable prompt prefix, never before it.
- With no TTY, an `ask` verdict is declined — never auto-approved.
- Memory goes pending → **a human approves** → loaded. Never auto-promote.
- `state.checkpoint()` upserts by step number; it must stay idempotent.
- `finops.py` is deterministic Python; no model call belongs in it. The LLM
  judge runs at *record* time and writes its verdict to the ledger, so the
  report stays pure arithmetic over recorded facts.
- No test may require an API key. Use `ScriptedModel` in `tests/conftest.py`.
- Deliberate shortcuts carry a `ponytail:` comment naming the upgrade path.
