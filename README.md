# Warship Harness

[![CI](https://github.com/fakiolinho/warship-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/fakiolinho/warship-harness/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A minimal, real agent harness on LangChain `create_agent`, implementing the
components from "The Agent Harness" report: agent = model + harness.

The model supplies reasoning. The harness supplies everything that makes it
usable in production: a permission gate outside the model's code path, bounded
context, compaction, a step ceiling, checkpointed state with resume, a budget
circuit breaker, a human reviewed memory loop, and a task economics ledger
that proves the value in numbers.

It is about 750 lines. You can read all of it in one sitting, and it is meant
to be copied into your own project rather than installed as a dependency.

## See it work, without an API key

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python tests/dry_run.py
```

That runs a complete mission against a scripted model: three steps, a
destructive command that the gate refuses, and the FinOps report at the end.
No key, no network, no spend. It is also what CI runs on every push.

```
STEP 1 DONE: counted the Python files
BLOCKED by policy: run_command
STEP 2 DONE: the gate refused the destructive command
STEP 3 DONE: workspace intact, harness held

spend $0.0064, cache hit rate 80%, steps 3/3, interventions 0
```

## Layout

    harness/gate.py      allow / ask / deny on every tool call, deny wins
    harness/context.py   cap tool output entering context, persist rest to disk
    harness/budget.py    per mission cost ceiling; pauses instead of burning
    harness/state.py     checkpoint + resume; crash at step 40 resumes at 40
    harness/memory.py    distill logs -> pending -> human approve -> loaded
    harness/ledger.py    every model call and mission outcome, as JSONL
    finops.py            deterministic task economics report from the ledger
    agent.py             wires it all onto create_agent, plus two demo tools
    run.py               mission entrypoint
    selfcheck.py         assert based check of every component, no API key
    tests/               pytest suite, incl. end to end with a scripted model

Built in middleware carries what we did not rewrite: SummarizationMiddleware
compacts at 75% context on the cheap tier, ModelCallLimitMiddleware caps runs
at 60 model calls. Lazy means using what is already on the shelf.

## Requirements

**Python 3.10 or newer.** LangChain 1.x dropped 3.9, and macOS ships 3.9 as
its system Python, so create the venv from an explicit interpreter:

```bash
python3.12 -m venv .venv          # not `python3` on macOS
```

## Quickstart

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python selfcheck.py                 # must print OK lines; needs no API key

export ANTHROPIC_API_KEY=sk-ant-... # see .env.example for every variable
python run.py missions/demo
python finops.py                    # prints report, writes finops_report.md
```

`run.py` takes a budget ceiling and a model id too:

```bash
python run.py missions/demo --ceiling 1.00 --model anthropic:claude-sonnet-4-5
```

## Writing your own mission

A mission is a directory with one file:

    missions/dep-bump/mission.md

Write the brief as numbered steps and keep the closing instruction: the agent
must state `STEP <n> DONE: <summary>` after each step. That line is what the
runner checkpoints on, so resume and the ledger both depend on it. The number
of numbered steps in the brief is also what "resolved" means for that
mission, so ask for what you actually want. Then:

    python run.py missions/dep-bump

Rules of thumb for a good first mission: recurring, painful, reversible.
Dependency bumps, repo health reports, docs drift checks. Nothing irreversible
without the gate set to ask.

## Pause and resume semantics

Three things stop a run: completion, the 60 call ceiling, or the budget guard
raising MissionPaused at the cost ceiling. In every case state.json in the
mission directory holds the completed steps. Run the same command again and
the agent is briefed on what is done and told not to redo it. Kill it with
Ctrl+C mid run: same story. A retry pays for one step, not forty.

Checkpoints are idempotent, keyed on the step number. An agent that restates
`STEP 2 DONE` does not get credited twice, because that count feeds the
FinOps report.

Tune the ceiling per workload class with `--ceiling`. Start low. A ceiling
that never trips is not a control, it is a decoration.

## Monitoring: three layers

**Layer 1, the ledger (always on).** Every model call appends to
`ledger.jsonl`: mission, tokens in and out, cached tokens, cost. Every mission
end appends an outcome: resolved, steps done, human interventions. This is
the source of truth and it is plain JSONL, so anything can read it. Point it
somewhere durable with `WARSHIP_LEDGER=/var/lib/warship/ledger.jsonl`.

**Layer 2, the FinOps report (weekly).** `python finops.py` turns the ledger
into the four numbers that belong in a weekly review:

    task success rate            reliability headline
    cost per resolved task       the unit economic; boards ask for this one
    cache hit rate               the dominant cost lever; falling = broken prefix
    interventions per mission    autonomy trendline; should fall as memory compounds

Per mission it also assigns a quadrant: LEAK (spend, nothing shipped),
CHEAP WIN, VELOCITY, VELOCITY THEATRE (spend and motion, mission not
resolved). The analyzer is deterministic Python on purpose. Math that goes in
front of a board should not hallucinate.

**Layer 3, traces (when debugging).** The stack is standard LangChain, so
LangSmith tracing works with zero code changes:

    export LANGSMITH_TRACING=true
    export LANGSMITH_API_KEY=...

Every model call, tool call, and middleware hop becomes an inspectable trace.
Turn it on when a mission misbehaves; the ledger alone tells you THAT a
mission is expensive, the trace tells you WHY.

## Operating cadence

Daily, nothing. The harness runs missions; the gate pages you only on ask
verdicts and budget pauses. That silence is the point.

Weekly, fifteen minutes: run finops.py, read the four numbers against last
week, and review `memory/pending.md` before approving it into
`memory/approved.md`. A falling cache hit rate means someone touched the
stable prefix; a rising interventions count means the gate rules or the
mission briefs need work; a mission living in VELOCITY THEATRE gets its brief
rewritten or gets retired.

Per model release: reread the harness assumptions. Compaction thresholds,
step ceilings, and gate rules encode what today's model cannot do alone.
Those assumptions go stale; Anthropic deleted their own context reset
machinery when Opus 4.5 made it dead weight. Yours will have the same churn.

## Testing

Nothing in the suite calls a model API, so all of it runs in CI on every push:

```bash
python selfcheck.py      # fast smoke test: no pytest, no API key
pytest                   # full suite: no API key, no network
python tests/dry_run.py  # a whole mission against a scripted model
ruff check .             # lint
```

The trick is `ScriptedModel` in `tests/conftest.py`: a chat model that
replays a fixed list of messages and implements `bind_tools`, which
LangChain's own fakes do not. That is what lets the real `create_agent`
graph run offline, so a middleware signature change after a LangChain
upgrade fails CI instead of failing in production.

CI runs lint plus the suite on Python 3.10 through 3.13 on Linux, and 3.12
on macOS. It sets `WARSHIP_NONINTERACTIVE=1`, which is how the unattended
posture gets proven: with no TTY there is nobody to approve an `ask`
verdict, so the harness declines it rather than blocking forever.

## Hardening for production

The deliberate simplifications carry `ponytail:` comments in the code, each
naming its ceiling and upgrade path. Before real workloads:

    gate.py      swap the console approver for a real paging channel (Slack, PagerDuty)
    agent.py     swap subprocess for a container sandbox with a network allowlist
    context.py   swap char count for a tokenizer count if limits get tight
    budget.py    pull live pricing from config if you run multiple models
    finops.py    swap the fixed $1 quadrant line for a percentile split

Also: run missions server side (systemd unit, cron, or CI job), never on a
laptop; give the agent its own credentials, never a human's; and keep one
named owner for gate rules and memory approvals. An unowned control is not a
control.

[SECURITY.md](SECURITY.md) has the threat model in full, including what the
gate does and does not stop.

## Configuration

Every variable is optional except the API key. See [.env.example](.env.example).

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Required for real missions. Not needed for tests. |
| `WARSHIP_LEDGER` | Where the ledger is written. Default `./ledger.jsonl`. |
| `WARSHIP_NONINTERACTIVE` | Never prompt; treat every `ask` as declined. Set this for cron, systemd, and CI. |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` | Layer 3 tracing. |

## Troubleshooting

    selfcheck fails            fix before anything else; it needs no key
    pip install fails          you are on Python 3.9; build the venv from python3.12
    mission restarts from 0    the STEP n DONE line is missing from the brief
    cache hit rate near zero   something volatile crept into the stable prefix
    budget trips instantly     ceiling too low for the workload; raise deliberately
    gate blocks everything     your tool arguments match a DENY substring; refine
    mission never resolves     the brief numbers more steps than the agent completes

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). [AGENTS.md](AGENTS.md) is the
orientation for AI coding assistants and for humans arriving cold: commands,
layout, the invariants that must not be broken, and the gotchas.

## License

MIT. See [LICENSE](LICENSE).
