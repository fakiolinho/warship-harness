## What this changes

<!-- One or two sentences. What behavior is different after this lands? -->

## Why

<!-- The problem this solves. Link an issue if there is one. -->

## Checklist

- [ ] `python selfcheck.py` passes
- [ ] `pytest` passes
- [ ] `ruff check .` passes
- [ ] Behavior changes have a test that would fail without this change
- [ ] No test I added requires `ANTHROPIC_API_KEY` or network access
- [ ] New deliberate shortcuts carry a `ponytail:` comment naming the
      ceiling and the upgrade path

## Invariants

<!--
AGENTS.md lists the invariants this project protects: the gate outside the
model's code path, the stable cacheable prefix, controls that can say no,
human-reviewed memory, idempotent checkpointing, deterministic FinOps math,
and an offline test suite.

Does this touch any of them? If yes, make the case. If no, say "none".
-->
