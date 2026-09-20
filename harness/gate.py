"""Permission gate: allow / ask / deny on every tool call, outside the model's code path.

Deny always wins. Start strict, loosen with evidence.

Why this is token aware rather than substring matching. A substring rule
asks "does this text contain `rm -rf`", which both misses `rm -r -f` and
fires on `git log --format='%h rm -rf'`. Neither is a close call: the
first runs, the second blocks honest work, and an operator who is blocked
for no reason starts loosening rules. So the command is split into the
segments a shell would run, each segment is tokenized with the shell's own
quoting rules, and rules match on the program being invoked and its flags.

What this still is not. It is a policy over one string, so anything that
obscures the program until runtime defeats it: a variable holding the
command, a script written to disk and then run, base64 in a heredoc. The
gate stops mistakes and opportunism. The boundary is the container.

Measured by `python evals/run_gate_eval.py` against a labelled corpus, so
changes here move a number instead of a belief.
"""
import os
import re
import shlex

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

# Substring backstop, kept so a rule can be added without writing code.
# The token rules below are what does the real work.
DENY = ()          # add a literal here to block it outright
ASK = ("git push", "deploy", "helm ", "kubectl apply", "send_email")

# Programs that execute whatever they are handed.
INTERPRETERS = {"sh", "bash", "zsh", "ksh", "dash", "python", "python3",
                "perl", "ruby", "node", "php", "eval", "source"}
# Programs whose whole purpose is destruction.
DESTRUCTIVE = {"mkfs", "shred", "srm", "wipefs"}
# Programs that move data off the machine.
EXFIL = {"nc", "ncat", "netcat", "scp", "sftp", "rsync", "ftp", "telnet"}
# Programs that fetch and are commonly piped into a shell.
FETCH = {"curl", "wget"}
# Paths that are never mission material.
SECRETS = re.compile(
    r"(\.ssh/|id_rsa|id_ed25519|\.aws/credentials|\.kube/config"
    r"|\.netrc|\.npmrc|/etc/shadow|\.env$|\.env\b)", re.IGNORECASE)
# Writing here changes the machine, not the workspace.
SYSTEM_PATHS = re.compile(r"^/(etc|usr|bin|sbin|boot|sys|proc|dev|var/lib)/")
# Statements that destroy data rather than files.
SQL_DESTRUCTIVE = re.compile(
    r"^\s*(drop|truncate)\s+(table|database|schema)\b", re.IGNORECASE)
# An inline program is only dangerous for what it does. Denying every
# `python -c` would block a great deal of honest work, so the rule looks
# at the program rather than the flag.
INLINE_DESTRUCTIVE = re.compile(
    r"rmtree|os\.remove|os\.unlink|os\.system|shutil\.move|subprocess"
    r"|unlink\(|\bexec\(|\beval\(", re.IGNORECASE)
# Escalation: whatever follows runs as another user.
ESCALATE = {"sudo", "doas", "su", "pkexec"}
# git subcommands that discard work.
GIT_DESTRUCTIVE = {("clean",), ("reset",)}
GIT_ASK = {"push", "tag", "remote"}

# Operators that separate one command from the next. `>` is deliberately
# absent: a redirect belongs to the command it follows.
OPERATORS = {"|", "||", "&&", ";", "&", "\n"}
_SUBSTITUTION = re.compile(r"\$\((.*?)\)|`(.*?)`|<\((.*?)\)", re.DOTALL)


def _lex(command: str) -> list[str]:
    """Tokenize the way a shell would, respecting quotes.

    Splitting on `;` with a regex is wrong in both directions: it misses
    `python -c "a; rmtree(...)"` because the payload is torn in half, and
    it blocks `echo "a; rm -rf /"` because a quoted string is read as a
    second command. Quote awareness is what makes segment rules mean
    anything.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:              # unbalanced quotes: crude but not silent
        return command.split()


def _segments(command: str) -> list[tuple[list[str], bool]]:
    """(tokens, receives_a_pipe) for each command the shell would run.

    Command substitutions are lexed too: `$(...)` runs before its parent.
    """
    segments: list[tuple[list[str], bool]] = []
    for group in _SUBSTITUTION.findall(command):
        for inner in group:
            if inner.strip():
                segments.append((_lex(inner), False))

    current: list[str] = []
    piped = False
    for token in _lex(_SUBSTITUTION.sub(" ", command)):
        if token in OPERATORS:
            if current:
                segments.append((current, piped))
            piped = token == "|"
            current = []
        else:
            current.append(token)
    if current:
        segments.append((current, piped))
    return segments


def _flags(args: list[str]) -> set[str]:
    """Short flags exploded (-rf -> r, f) plus long flags by name.

    Lowercased: a gate that reads -RF differently from -rf is a gate with
    a trivial bypass, and deny is the safe direction to be wrong in.
    """
    out: set[str] = set()
    for a in args:
        if a.startswith("--"):
            out.add(a[2:].split("=")[0].lower())
        elif a.startswith("-") and len(a) > 1:
            out.update(a[1:].lower())
    return out


def _segment_verdict(tokens: list[str], piped_into: bool) -> str | None:
    if not tokens:
        return None
    segment = " ".join(tokens)
    # Lowercased: a case insensitive filesystem will happily run RM, and
    # deny is the safe direction to be wrong in.
    exe = os.path.basename(tokens[0]).lower()
    args = tokens[1:]
    flags = _flags(args)

    if exe in ESCALATE:
        return "deny"

    if SQL_DESTRUCTIVE.search(segment):
        return "deny"

    # A redirect that writes outside the workspace into system state.
    for i, tok in enumerate(tokens):
        if (tok in (">", ">>") and i + 1 < len(tokens)
                and SYSTEM_PATHS.match(tokens[i + 1])):
            return "deny"

    # Anything reading a private key or credential file.
    if any(SECRETS.search(a) for a in args):
        return "deny"

    # An interpreter fed from a pipe is running code from somewhere else,
    # which is unambiguous. An inline program is judged on its contents.
    if exe in INTERPRETERS:
        if piped_into:
            return "deny"
        # The inline program is one token; judge that, not the whole line.
        if "c" in flags and any(INLINE_DESTRUCTIVE.search(a) for a in args):
            return "deny"

    if exe in DESTRUCTIVE or exe.startswith("mkfs."):
        return "deny"

    if exe in EXFIL:
        return "deny"

    if exe in FETCH:
        return "deny"

    if exe == "rm" and {"r", "recursive"} & flags and {"f", "force"} & flags:
        return "deny"

    if exe == "find" and ("-delete" in args or "-exec" in args):
        return "deny"

    if exe == "dd" and any(a.startswith("of=/dev") for a in args):
        return "deny"

    if exe == "truncate" and any(a in ("-s", "--size") for a in args):
        return "deny"

    # `: > file` is the shell idiom for emptying a file.
    if exe in (":", "true") and ">" in tokens:
        return "deny"

    if exe == "git" and args:
        sub = args[0]
        if (sub,) in GIT_DESTRUCTIVE and ({"hard", "force", "f", "x", "d"} & flags):
            return "deny"
        if sub in GIT_ASK:
            return "ask"

    if exe in ("kubectl", "helm", "terraform", "npm", "gh", "docker"):
        mutating = {"apply", "upgrade", "install", "publish", "merge",
                    "destroy", "delete", "push"}
        if any(a in mutating for a in args):
            return "ask"

    return None


def decide(tool_name: str, tool_args: dict) -> str:
    """Pure decision function. Returns 'allow' | 'ask' | 'deny'.

    Deny beats ask beats allow, across every segment of the command.
    """
    command = str(tool_args.get("command", "")) if isinstance(tool_args, dict) else ""
    blob = f"{tool_name} {tool_args}".lower()

    # Non shell tools: judge the whole blob, and guard their paths.
    if not command:
        if any(bad in blob for bad in DENY) or SECRETS.search(blob):
            return "deny"
        return "ask" if any(g in blob for g in ASK) else "allow"

    verdicts = []
    for tokens, piped in _segments(command):
        v = _segment_verdict(tokens, piped)
        if v:
            verdicts.append(v)

    # The substring lists stay as a backstop for rules added by hand.
    low = command.lower()
    if any(bad in low for bad in DENY):
        verdicts.append("deny")
    if any(g in low for g in ASK):
        verdicts.append("ask")

    if "deny" in verdicts:
        return "deny"
    if "ask" in verdicts:
        return "ask"
    return "allow"


class PermissionGate(AgentMiddleware):
    """Wraps every tool call. The model never sees this code path."""

    def __init__(self, approver=None):
        """approver: callable(tool_name, tool_args) -> bool. Defaults to a
        console prompt; tests and unattended runs inject their own."""
        super().__init__()
        self.interventions = 0   # human touches, feeds the ledger outcome
        self.approver = approver or _console_approver

    def wrap_tool_call(self, request, handler):
        name = request.tool_call["name"]
        args = request.tool_call.get("args", {})
        verdict = decide(name, args)
        if verdict == "deny":
            return ToolMessage(
                content=f"BLOCKED by policy: {name}",
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        if verdict == "ask":
            self.interventions += 1
            if not self.approver(name, args):
                return ToolMessage(
                    content="Human declined the action.",
                    tool_call_id=request.tool_call["id"],
                    status="error",
                )
        return handler(request)


def _console_approver(tool_name: str, tool_args: dict) -> bool:
    """ponytail: console prompt stands in for a real paging channel
    (Slack, PagerDuty). Upgrade path: swap this for a webhook.

    With no TTY (CI, cron, systemd) there is nobody to ask, so the answer
    is no. An unattended run must never silently approve itself.
    """
    if os.environ.get("WARSHIP_NONINTERACTIVE") or not _stdin_is_tty():
        print(f"[GATE] {tool_name} needs approval; no TTY, so: declined")
        return False
    return input(f"[GATE] approve {tool_name}? y/N ").strip().lower() == "y"


def _stdin_is_tty() -> bool:
    import sys
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False
