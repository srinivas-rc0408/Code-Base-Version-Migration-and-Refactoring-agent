"""Isolated execution: container-backed verification and git snapshot/rollback."""

from mra.sandbox.git_tools import changed_paths, diff, rollback, snapshot
from mra.sandbox.runner import SandboxRunner, failure_signature, normalize_message
from mra.sandbox.workspace import UnsafeRepoError, copy_repo

__all__ = [
    "SandboxRunner",
    "UnsafeRepoError",
    "changed_paths",
    "copy_repo",
    "diff",
    "failure_signature",
    "normalize_message",
    "rollback",
    "snapshot",
]
