"""Wire the harness stack onto LangChain's create_agent.

agent = model + harness. The model supplies reasoning; everything below
is the harness: gate, bounded context, compaction, step ceiling, budget.
"""
import pathlib
import subprocess

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    SummarizationMiddleware,
)
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool

from harness import BoundedToolOutput, BudgetGuard, PermissionGate, memory

DEFAULT_MODEL = "anthropic:claude-sonnet-4-5"
COMPACTION_MODEL = "anthropic:claude-haiku-4-5"   # cheap tier compacts
RUN_LIMIT = 60
COMMAND_TIMEOUT_S = 120
MAX_TOKENS = 8_000

# Anthropic does not cache unless asked. Without a breakpoint the cache hit
# rate is structurally 0%, however carefully the prefix is ordered, and the
# headline FinOps number reads like a broken prefix instead of a switch that
# was never flipped. This puts one breakpoint at the end of the request, so
# everything before it (system prompt, tools, prior turns) is cacheable.
#
# Two caveats worth knowing before reading the number:
#   * A prefix shorter than the model's minimum silently will not cache.
#     Sonnet 4.5 needs 1024 tokens; short missions never reach it.
#   * Writes cost 1.25x and reads 0.1x, so a prefix reused only once is
#     roughly break even. Caching pays on long missions, not short ones.
CACHE_CONTROL = {"type": "ephemeral"}   # 5 minute TTL


def default_model(model_id: str = DEFAULT_MODEL) -> ChatAnthropic:
    """The mission model, with prompt caching switched on."""
    return ChatAnthropic(
        model=model_id.removeprefix("anthropic:"),
        max_tokens=MAX_TOKENS,
        model_kwargs={"cache_control": CACHE_CONTROL},
    )

# The workspace root every tool is confined to. run.py sets it per mission.
# ponytail: a process wide global stands in for a real sandbox boundary.
# Upgrade path: a container whose filesystem *is* the workspace.
WORKSPACE = pathlib.Path.cwd()


def set_workspace(root: pathlib.Path) -> None:
    global WORKSPACE
    WORKSPACE = pathlib.Path(root).resolve()


def _inside_workspace(path: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(WORKSPACE)
    except ValueError:
        return False
    return True


@tool
def read_file(path: str) -> str:
    """Read a text file from the mission workspace."""
    p = pathlib.Path(path)
    if not _inside_workspace(p):
        # The brief says "work inside this directory". Saying it is not
        # enforcing it: a model that wanders to ~/.ssh/id_rsa is one
        # bad step away, and the gate only sees shell strings.
        return f"BLOCKED: {path} is outside the workspace ({WORKSPACE})"
    try:
        return p.read_text()
    except (OSError, UnicodeDecodeError) as e:
        return f"ERROR reading {path}: {e}"


@tool
def run_command(command: str) -> str:
    """Run a shell command in the mission workspace."""
    # ponytail: subprocess in cwd stands in for a real sandbox.
    # Upgrade path: Docker / firejail with a network allowlist.
    try:
        out = subprocess.run(command, shell=True, capture_output=True,
                             text=True, timeout=COMMAND_TIMEOUT_S,
                             cwd=WORKSPACE)
    except subprocess.TimeoutExpired:
        # A hung command must cost one tool call, not the whole mission.
        return f"ERROR: command timed out after {COMMAND_TIMEOUT_S}s: {command}"
    return (out.stdout + out.stderr) or f"(no output, exit {out.returncode})"


def build_agent(mission_dir: pathlib.Path, budget: BudgetGuard,
                model: str | object = DEFAULT_MODEL,
                approver=None, compaction_model: str | object | None = None):
    """Assemble the agent. `model` and `approver` are injectable so the
    whole stack can be exercised in tests without an API key or a human.

    A model id string is built through default_model() so caching is on by
    default; pass a model instance to opt out or to inject a fake.
    """
    if isinstance(model, str):
        model = default_model(model)
    approved_memory = memory.load(mission_dir.parent / "memory")
    system = (
        "You are a maintenance agent. Work one step at a time. "
        "After each meaningful step, state STEP <n> DONE: <summary>.\n"
        # Stable prefix above; approved memory below it, so the cache
        # over the prefix survives memory updates.
        + (f"\nKnown facts from previous missions:\n{approved_memory}"
           if approved_memory else "")
    )
    gate = PermissionGate(approver=approver)
    middleware = [
        gate,
        BoundedToolOutput(mission_dir / "artifacts"),
    ]
    summarizer = compaction_model if compaction_model is not None else (
        COMPACTION_MODEL if isinstance(model, str) else None)
    if summarizer is not None:
        middleware.append(SummarizationMiddleware(
            model=summarizer,
            trigger=("fraction", 0.75),
        ))
    middleware.append(
        ModelCallLimitMiddleware(run_limit=RUN_LIMIT, exit_behavior="end"))
    middleware.append(budget)
    agent = create_agent(
        model=model,
        tools=[read_file, run_command],
        system_prompt=system,
        middleware=middleware,
    )
    return agent, gate
