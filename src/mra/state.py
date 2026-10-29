"""``MigrationState`` — the agent's working memory.

A transcription of the ``mra:migration_state`` schema in ``docs/03_SRS.md``
§4.1, which is the authoritative shape (golden rule 4). Nothing is invented
here; if a field changes it changes in the SRS first and this follows.

``total=False`` because the state is filled in as the loop runs: MAP writes
``call_sites``/``dep_graph``, PLAN writes ``edit_batches``, CORRECT writes
``fix_attempts``, and every LLM call adds to ``tokens``.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

FileStatus = Literal["pending", "in_progress", "migrated", "partial", "verified", "failed"]


class Contract(TypedDict, total=False):
    """What is being migrated, from the task's ``ground_truth.json``."""

    task_id: str
    source_api: str
    target_api: str
    guide_excerpt: str
    #: Ruff rule codes the target API itself triggers; the report exempts them.
    expected_lint: list[str]
    #: Regexes a corrective patch may not add (anti-reversal guard).
    forbidden_patterns: list[str]
    #: A corrective patch may drop top-level definitions or shrink a file by >50%.
    allow_deletion: bool


class Tokens(TypedDict):
    """M3's raw material: tokens per model tier, plus tool calls."""

    pro_in: int
    pro_out: int
    flash_in: int
    flash_out: int
    tool_calls: int


class MigrationState(TypedDict, total=False):
    run_id: str
    repo_path: str
    contract: Contract
    call_sites: dict[str, list[dict[str, Any]]]
    dep_graph: dict[str, list[str]]
    edit_batches: list[list[str]]
    file_status: dict[str, FileStatus]
    current_batch: int
    last_test_report: dict[str, Any]
    #: failure signature -> attempts spent on it. The retry ceiling (NFR-1)
    #: is counted per signature, not per run, which is why this is a map.
    fix_attempts: dict[str, int]
    trajectory: list[dict[str, Any]]
    #: Rolling progress note carried into the next LLM prompt. Bounded by
    #: mra.memory so the context does not grow with the repo (NFR-12).
    summary: str
    #: The step just taken, as {action, detail}. A single slot, not a list:
    #: the checkpointer keeps one snapshot per step, so the history is the
    #: audit log and mra.graph reconstructs trajectory.json from it.
    note: dict[str, Any]
    tokens: Tokens
    done: bool


def new_tokens() -> Tokens:
    return Tokens(pro_in=0, pro_out=0, flash_in=0, flash_out=0, tool_calls=0)


def new_state(run_id: str, repo_path: str, contract: Contract) -> MigrationState:
    """A state with every required field present and the counters zeroed."""
    return MigrationState(
        run_id=run_id,
        repo_path=repo_path,
        contract=contract,
        file_status={},
        current_batch=0,
        fix_attempts={},
        trajectory=[],
        tokens=new_tokens(),
        done=False,
    )
