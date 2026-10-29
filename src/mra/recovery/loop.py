"""The recovery loop: EDIT -> TEST -> CORRECT -> TEST -> ... -> green or give up.

This is FR-7 and FR-9 in one function. A plain function on purpose, and it
stayed one after P4 added the LangGraph wiring: a state machine whose
mechanics are only observable through a framework is a state machine nobody
can test. ``mra/graph.py`` routes CORRECT/TEST itself and shares only the cap
defined here; this loop is what ``mra.run`` drives and what the P3 tests
exercise directly.

Two stop conditions, both required:

* **green** — no failures and no errors. Done.
* **capped** — a failure signature has consumed ``MAX_FIX_ATTEMPTS`` (NFR-1).
  The run gives up, is flagged for a human, and says which signature beat it.
  Without the cap a corrector that cannot fix a break retries forever; the
  signature (not the raw message) is what makes "the same failure again"
  decidable across runs, which is why P0 normalized it so aggressively.

Every round is snapshotted before the corrector runs, so a corrective patch
that touches the test oracle is reverted rather than merely reported (NB-4).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from mra.sandbox import changed_paths, rollback, snapshot
from mra.sandbox.runner import SandboxRunner

DEFAULT_MAX_FIX_ATTEMPTS = 3


class Corrector(Protocol):
    """Anything that can repair a failing tree in place.

    Returns the repo-relative files it changed. The loop cares about the
    mechanics; whether the fix came from an LLM, a codemod or a stub is the
    corrector's business — which is what lets the loop be tested without a key.
    """

    def __call__(
        self, repo: Path, failure: dict[str, Any], context: dict[str, Any]
    ) -> list[str]: ...


class Trajectory(Protocol):
    def record(self, node: str, action: str, **detail: Any) -> None: ...


def is_green(report: dict[str, Any]) -> bool:
    return report.get("failed", 0) == 0 and report.get("errors", 0) == 0


def _next_failure(
    report: dict[str, Any], attempts: dict[str, int], cap: int
) -> dict[str, Any] | None:
    """The first failure that has budget left.

    Picking ``failures[0]`` unconditionally would spin on one stuck break until
    the cap and give up while other, fixable failures were never attempted.
    """
    for failure in report.get("failures", []):
        if attempts.get(failure["signature"], 0) < cap:
            return failure
    return None


def _test_oracle_touched(repo: Path, base_sha: str) -> list[str]:
    from mra.nodes.correct_node import is_test_path

    return [path for path in changed_paths(repo, base_sha) if is_test_path(path)]


def recover(
    repo: Path | str,
    report: dict[str, Any],
    *,
    runner: SandboxRunner,
    corrector: Corrector,
    task_id: str,
    trajectory: Trajectory,
    run_id: str | None = None,
    context: dict[str, Any] | None = None,
    fix_attempts: dict[str, int] | None = None,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    """Drive CORRECT/TEST until the suite is green or a signature hits the cap.

    Args:
        repo: the writable copy. Never the corpus source.
        report: the ``mra:test_report`` from the TEST that just failed.
        runner: the sandbox verifier; every re-test runs in a container.
        corrector: applies one corrective patch per round.
        trajectory: gets a CORRECT and a TEST event per round (SRS §4.1).
        fix_attempts: the live ``MigrationState.fix_attempts`` map, mutated here.
        max_attempts: per-signature ceiling; defaults to ``MRA_MAX_FIX_ATTEMPTS``.

    Returns:
        ``{outcome, report, rounds, flagged, signature, corrections}`` —
        ``outcome`` is ``"success"`` or ``"gave_up"``.
    """
    from mra.nodes.correct_node import RETRY_ACTION, last_rejection, model_calls, retries

    repo = Path(repo)
    cap = (
        max_attempts
        if max_attempts is not None
        else int(os.getenv("MRA_MAX_FIX_ATTEMPTS", str(DEFAULT_MAX_FIX_ATTEMPTS)))
    )
    attempts = fix_attempts if fix_attempts is not None else {}
    context = context or {}
    corrections: list[dict[str, Any]] = []
    rounds = 0

    while not is_green(report):
        failure = _next_failure(report, attempts, cap)
        if failure is None:
            blocked = sorted({f["signature"] for f in report.get("failures", [])})
            trajectory.record(
                "CORRECT",
                f"gave up after {cap} attempt(s) per signature",
                signatures=blocked,
                attempts={s: attempts.get(s, 0) for s in blocked},
                flagged=True,
            )
            return {
                "outcome": "gave_up",
                "report": report,
                "rounds": rounds,
                "flagged": True,
                "signature": blocked[0] if blocked else None,
                "corrections": corrections,
            }

        signature = failure["signature"]
        attempts[signature] = attempts.get(signature, 0) + 1
        rounds += 1

        base_sha = snapshot(repo, f"pre-correction {rounds} ({signature})")
        seen = len(model_calls(corrector))
        changed = corrector(repo, failure, context)
        for retry in retries(model_calls(corrector)[seen:]):
            trajectory.record(
                "CORRECT", RETRY_ACTION, signature=signature, attempt=attempts[signature], **retry
            )

        tampered = _test_oracle_touched(repo, base_sha)
        if tampered:
            # Golden rule 1. Revert first, report second: a patch that edits the
            # oracle must not survive long enough to be tested against it.
            rollback(repo, base_sha)
            trajectory.record(
                "CORRECT",
                "rejected a patch that edited the test oracle (NB-4)",
                signature=signature,
                attempt=attempts[signature],
                files=tampered,
            )
            corrections.append(
                {
                    "signature": signature,
                    "attempt": attempts[signature],
                    "changed": [],
                    "rejected": tampered,
                }
            )
            continue

        sha = snapshot(repo, f"correction {rounds} for {signature}")
        # A patch the anti-reversal guard refused: unapplied, attempt still spent.
        rejected = {"rejected": reason} if (reason := last_rejection(corrector)) else {}
        trajectory.record(
            "CORRECT",
            f"attempt {attempts[signature]}/{cap} on {failure['nodeid']}",
            signature=signature,
            attempt=attempts[signature],
            exc_type=failure.get("exc_type"),
            files=changed,
            sha=sha,
            **rejected,
        )
        corrections.append(
            {
                "signature": signature,
                "attempt": attempts[signature],
                "changed": changed,
                "sha": sha,
                **rejected,
            }
        )

        report = runner.run(repo, task_id=task_id, phase="recovery", run_id=run_id, lint=False)
        trajectory.record(
            "TEST",
            f"recovery suite after attempt {attempts[signature]}",
            total=report["total"],
            passed=report["passed"],
            failed=report["failed"],
            errors=report["errors"],
        )

    trajectory.record(
        "CORRECT", f"recovered to green in {rounds} attempt(s)", rounds=rounds, flagged=False
    )
    return {
        "outcome": "success",
        "report": report,
        "rounds": rounds,
        "flagged": False,
        "signature": None,
        "corrections": corrections,
    }
