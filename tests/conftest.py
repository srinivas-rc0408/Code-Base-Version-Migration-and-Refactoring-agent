"""Shared test helpers. The suite runs in parallel (pytest-xdist)."""

from __future__ import annotations

import uuid


def unique_id(name: str) -> str:
    """A run id no other test, worker or concurrent session can share.

    The run id names the sandbox container (``mra-<run_id>``) and the run
    directory, so two parallel tests with one id would collide on both.
    """
    return f"{name}-{uuid.uuid4().hex[:8]}"
