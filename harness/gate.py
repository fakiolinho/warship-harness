"""Permission gate: allow / ask / deny on every tool call, outside the model's code path.

Deny always wins. Start strict, loosen with evidence.
"""
import os

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

DENY = ("rm -rf", "curl ", "wget ", "sudo ", "> /etc/", "drop table", "mkfs")
ASK = ("git push", "deploy", "helm ", "kubectl apply", "send_email")


def decide(tool_name: str, tool_args: dict) -> str:
    """Pure decision function. Returns 'allow' | 'ask' | 'deny'.

    Matching is case insensitive: `DROP TABLE` and `drop table` are the
    same instruction to a shell or a database, so they get the same verdict.
    Keep the DENY and ASK entries lowercase.
    """
    blob = f"{tool_name} {tool_args}".lower()
    if any(bad in blob for bad in DENY):
        return "deny"
    if any(gate in blob for gate in ASK):
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
