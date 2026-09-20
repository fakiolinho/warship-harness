# Security policy

## Reporting a vulnerability

Do not open a public issue. Report privately through GitHub's
[Report a vulnerability](https://github.com/fakiolinho/warship-harness/security/advisories/new)
form, or email <fakiolasmarios@gmail.com>.

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
- `harness/gate.py` decides with case-insensitive substring matching. It
  stops the obvious and the accidental. It is not an adversarial parser:
  `rm -r -f`, a base64'd payload, or a script written to disk and then run
  will pass it.

`read_file` is confined to the workspace root, and the gate's deny list
always wins over its ask list. Those are real controls. They are not a
substitute for the ones below.

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
