# Security policy

## Reporting a vulnerability

Do not open a public issue. Report privately through GitHub's
[Report a vulnerability](https://github.com/fakiolinho/warship-harness/security/advisories/new)
form, or email <m.fakiolas@hotmail.gr>.

Please include what an attacker gains, the smallest reproduction you have,
and the versions of Python and `langchain` you tested on. Expect an
acknowledgement within a week.

## What this project is, in threat model terms

This harness runs a language model that can execute shell commands and read
files. That is the point of it, and it means **the harness is a sandbox in
the loose sense, not in the hardened sense.** Two of its controls are
deliberate simplifications, each marked `ponytail:` in the source:

- `agent.py` runs commands through `subprocess` with `shell=True` in the
  workspace directory. There is no syscall filter, no network allowlist,
  and no resource limit. A command the gate allows runs with the full
  privileges of the user that started the mission.
- `harness/gate.py` parses the command into the segments a shell would run
  and matches on the program and its flags, which is why `rm -r -f` and
  `cat x | sh` are caught where substring matching missed them. It is
  still a policy over one string: anything that hides the program until
  runtime defeats it — a variable holding the command, a script written to
  disk and then run, base64 in a heredoc. `python evals/run_gate_eval.py`
  reports what it currently catches.

**`read_file` is confined to the workspace; `run_command` is not and
cannot be.** `sh -c` reaches anything the invoking user reaches, so
`cat /etc/passwd` succeeds. The confinement is defence in depth against a
model that wanders, not a boundary against one being steered. Do not read
it as more than that: an asymmetric control mistaken for a real one is
worse than no control.

The real boundary is the process boundary. See `Dockerfile`. CI builds it
on every push and asserts that the agent user cannot write to `/etc`, so
the image itself is tested; the bind-mount and `-u` setup in the README
is not, because CI runs it without host mounts.

## Prompt injection through tool output

Tool output is whatever was in the files and commands the agent touched,
so a repository can write text into the prompt of anything reading that
output. Two places consume it:

- **The model itself.** Standard agent exposure; the gate is what stands
  between an injected instruction and a destructive action.
- **The LLM judge**, which grades the transcript. An injected verdict
  would be written to the ledger as fact. The transcript is fenced in
  tags whose closing sequence is neutralized, and the grading instruction
  is repeated after the data so a forged one is not the last word. The
  judge also reports `injection_attempted`, which the FinOps report
  escalates. Measured on `claude-sonnet-4-5`, the judge refused all four
  payloads and flagged every one; run
  `python evals/run_online_evals.py --only judge_injection --repeat 10`
  to re-measure, because one sample is not a rate. This is still
  mitigation, not a boundary — the payloads are ones we thought of — so
  treat a verdict from a mission that touched untrusted content as
  advisory.

**The agent has no equivalent defence.** The judge reads tool output to
grade it; the agent reads tool output to act on it. Nothing fences the
agent's own context, so an injected instruction reaches the model that
issues tool calls, and the permission gate is the only thing between that
instruction and the command it asks for. That is the single strongest
argument for running missions in the container.

## Tracing sends workspace content to a third party

`ledger.jsonl` records token counts and costs, never prompt or response
content. **LangSmith tracing is different.** With `LANGSMITH_TRACING=true`,
prompts, tool output, and the file contents the agent read are sent to
LangSmith. That is the point of tracing, and it is fine for your own
repository; think before pointing it at anything sensitive.

## Running this safely

1. **Run missions server side**, under systemd, cron, or CI. Not on a
   laptop that holds your SSH keys and your browser profile.
2. **Give the agent its own credentials**, scoped to what the mission needs
   and revocable on their own. Never a human's personal token.
3. **Run in a container** whose filesystem is the workspace, with the
   network restricted to what the mission needs. This is the upgrade path
   named in `agent.py`, and it is the single highest-value hardening step.
4. **Set `WARSHIP_NONINTERACTIVE=1`** for unattended runs. With no TTY
   there is nobody to approve an `ask` verdict, so the harness declines it
   rather than proceeding. Verify this holds in your deployment.
5. **Keep the budget ceiling low** and tune it upward deliberately. A
   ceiling that never trips is not a control, it is a decoration.
6. **Review `memory/pending.md` before approving it.** Approved memory is
   loaded into the system prompt of every later mission. It is a durable
   injection surface, and the human review step is what protects it.
7. **Treat mission briefs as code.** A brief is an instruction to something
   that can run commands. Review changes to `missions/` the way you review
   a shell script.

## Secrets

`ANTHROPIC_API_KEY` is read from the environment and never written to disk
by this project. `ledger.jsonl` records token counts and costs, never
prompt or response content. Mission `artifacts/` and `state.json`, however,
hold whatever the tools returned, so treat them as workspace-sensitive.
Both are gitignored.

## Supported versions

This is a reference implementation at `0.1.x`. Fixes land on `main`; there
are no backported release branches.
