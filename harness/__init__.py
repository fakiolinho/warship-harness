"""The harness: everything around the model that makes it usable in production.

agent = model + harness. The model supplies reasoning; these modules supply
the permission gate, bounded context, budget ceiling, checkpointed state,
reviewed memory, and the task economics ledger.
"""

from . import ledger, memory, state
from .budget import BudgetGuard, MissionPaused
from .context import BoundedToolOutput, bounded
from .gate import PermissionGate, decide

__all__ = [
    "BoundedToolOutput",
    "BudgetGuard",
    "MissionPaused",
    "PermissionGate",
    "bounded",
    "decide",
    "ledger",
    "memory",
    "state",
]
