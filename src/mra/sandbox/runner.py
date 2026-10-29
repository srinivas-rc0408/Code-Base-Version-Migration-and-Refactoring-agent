"""Run a repo's test suite inside an isolated container and normalize the result.

This is the verifier half of the TEST node (SRS FR-6). It never executes repo
code on the host: the input tree is bind-mounted read-only, copied to a
writable path *inside* the container, and only the container runs pytest.

The only output anyone downstream may read is the ``mra:test_report`` shape
from ``docs/03_SRS.md`` §4.3 — raw ``pytest-json-report`` output is an
implementation detail of this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Literal

Phase = Literal["pre", "post", "recovery"]

#: Where the input tree, its writable copy, and the output dir live *inside* the
#: container. The writable copy is what pytest sees, so tracebacks are rooted here.
CONTAINER_REPO = "/work/repo"
CONTAINER_REPO_RW = "/work/repo_rw"
CONTAINER_OUT = "/work/out"

#: Truncation for the trace handed to the recovery model (NFR-12: never send
#: more context than the fix needs).
TRACE_MAX_CHARS = 4000

#: Grace added to the in-container timeout before the host gives up on `docker`
#: itself (image pull, container start). The inner timeout is the one that
#: implements NFR-4; this only stops a wedged runtime from hanging a run.
HOST_TIMEOUT_GRACE_SEC = 60

_ABS_PATH = re.compile(r"(/[\w.\-]+)+/")
_HEX_ADDR = re.compile(r"0x[0-9a-fA-F]+")
_DIGITS = re.compile(r"\d+")
_WHITESPACE = re.compile(r"\s+")
_EXC_LINE = re.compile(r"^E\s+([A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit))\b", re.M)


def normalize_message(message: str) -> str:
    """Strip everything run-specific from a failure message.

    Absolute paths, memory addresses and every digit run are volatile — a
    failing ``assert make_timestamp().year == 1999`` embeds the current clock
    in its own message — so a signature built on the raw text would differ on
    every run and the retry ceiling (NFR-1) would never trigger.
    """
    text = _ABS_PATH.sub("", message)
    text = _HEX_ADDR.sub("<addr>", text)
    text = _DIGITS.sub("<n>", text)
    return _WHITESPACE.sub(" ", text).strip()


#: How a test that needs the network fails under ``--network none`` (NB-5).
NETWORK_ERROR = re.compile(
    r"name resolution|getaddrinfo|Name or service not known|Network is unreachable|"
    r"nodename nor servname|gaierror|ConnectionRefused|Errno -3|Errno 101",
    re.I,
)


def needs_network(report: dict[str, Any]) -> list[str]:
    """Failing tests whose error is the sandbox's missing network, not the code."""
    return [
        f["nodeid"]
        for f in report.get("failures", [])
        if NETWORK_ERROR.search(
            f"{f.get('exc_type', '')} {f.get('message', '')} {f.get('trace', '')}"
        )
    ]


def failure_signature(nodeid: str, exc_type: str, message: str) -> str:
    """Stable id for a recurring failure: hash of (nodeid, exc_type, normalized message).

    The recovery loop counts attempts per signature, so this must be identical
    across runs of the same break and different across different breaks.
    """
    payload = f"{nodeid}|{exc_type}|{normalize_message(message)}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _exc_type_from(entry: dict[str, Any]) -> str:
    """Best-effort exception class name for one raw pytest-json-report entry."""
    # The last traceback frame carries the bare exception name for test failures.
    frames = entry.get("traceback") or []
    if frames:
        candidate = str(frames[-1].get("message", "")).split(":")[0].strip()
        if candidate.isidentifier():
            return candidate
    # Collection errors have no crash/traceback, only a longrepr blob.
    match = _EXC_LINE.search(str(entry.get("longrepr", "")))
    if match:
        return match.group(1)
    return "Failure"


def _relative(path: str) -> str:
    """Container-absolute path -> repo-relative, so reports are host-portable."""
    prefix = f"{CONTAINER_REPO_RW}/"
    return path[len(prefix) :] if path.startswith(prefix) else path


def _failure_from_test(test: dict[str, Any]) -> dict[str, Any]:
    """Normalize one failed/errored test into a test_report.failures[] entry."""
    # A test can blow up in setup or teardown, not just in the call phase.
    stage = next(
        (
            test[s]
            for s in ("call", "setup", "teardown")
            if isinstance(test.get(s), dict) and test[s].get("outcome") != "passed"
        ),
        {},
    )
    crash = stage.get("crash") or {}
    nodeid = test["nodeid"]
    exc_type = _exc_type_from(stage)
    message = str(crash.get("message", "")).strip()
    return {
        "nodeid": nodeid,
        "signature": failure_signature(nodeid, exc_type, message),
        "exc_type": exc_type,
        "message": message,
        "trace": str(stage.get("longrepr", ""))[:TRACE_MAX_CHARS],
        "file": _relative(str(crash.get("path", ""))),
        "line": int(crash.get("lineno", 0) or 0),
    }


def _failure_from_collector(collector: dict[str, Any]) -> dict[str, Any]:
    """Normalize a collection error (syntax error, bad import) the same way.

    Without this a repo that no longer parses reports zero failures and reads
    as green, which is the worst possible lie for a verifier to tell.
    """
    nodeid = collector.get("nodeid") or "<collection>"
    longrepr = str(collector.get("longrepr", ""))
    exc_type = _exc_type_from(collector)
    message = longrepr.strip().splitlines()[-1].strip() if longrepr.strip() else "collection error"
    return {
        "nodeid": nodeid,
        "signature": failure_signature(nodeid, exc_type, message),
        "exc_type": exc_type,
        "message": message,
        "trace": longrepr[:TRACE_MAX_CHARS],
        "file": nodeid,
        "line": 0,
    }


def _lint_counts(ruff_json: Path) -> dict[str, int]:
    """Ruff emits one flat diagnostic list with no severity split, so all are errors."""
    try:
        diagnostics = json.loads(ruff_json.read_text())
    except (OSError, json.JSONDecodeError):
        return {"errors": 0, "warnings": 0}
    return {"errors": len(diagnostics), "warnings": 0}


class SandboxRunner:
    """Runs a repo's suite in one throwaway container and returns a test_report.

    The container gets ``--network none`` (NB-5), the input tree read-only
    (NB-6), and the calling user's uid:gid so bind-mounted output is not
    root-owned on a Linux host.
    """

    def __init__(
        self,
        image: str | None = None,
        runtime: str | None = None,
        timeout_s: int | None = None,
        runs_dir: Path | str = "runs",
    ) -> None:
        self.image = image or os.getenv("MRA_SANDBOX_IMAGE", "mra-sandbox:py312")
        self.runtime = runtime or os.getenv("MRA_CONTAINER_RUNTIME", "docker")
        self.timeout_s = timeout_s or int(os.getenv("MRA_PYTEST_TIMEOUT_SEC", "120"))
        self.runs_dir = Path(runs_dir)

    def _script(self, lint: bool, coverage: bool = False) -> str:
        """Shell run inside the container. `timeout` here is what enforces NFR-4."""
        # Coverage is opt-in (the run report's evidence pass); without it the
        # script is byte-for-byte the one every benchmark run used.
        runner = (
            "python -m coverage run --data-file=/tmp/.coverage -m pytest"
            if coverage
            else "python -m pytest"
        )
        lines = [
            "set -u",
            f"cp -a {CONTAINER_REPO} {CONTAINER_REPO_RW}",
            f"cd {CONTAINER_REPO_RW}",
            # No `pip install`: the sandbox has no network (NB-5), and an editable
            # install would need to fetch its build backend. src-layout and flat
            # layout are both covered by putting each on the path.
            f"export PYTHONPATH={CONTAINER_REPO_RW}/src:{CONTAINER_REPO_RW}",
            f"timeout -k 5 {self.timeout_s}s {runner}"
            f" --json-report --json-report-file={CONTAINER_OUT}/pytest_raw.json"
            " -p no:cacheprovider -q",
            "pytest_rc=$?",
        ]
        if coverage:
            lines.append(
                f"python -m coverage json --data-file=/tmp/.coverage"
                f" -o {CONTAINER_OUT}/coverage.json >/dev/null 2>&1 || true"
            )
        if lint:
            lines.append(
                f"ruff check --output-format json . > {CONTAINER_OUT}/ruff.json 2>/dev/null || true"
            )
        lines.append("exit $pytest_rc")
        return "\n".join(lines)

    def _docker_argv(
        self, repo: Path, out_dir: Path, name: str, lint: bool, coverage: bool = False
    ) -> list[str]:
        return [
            self.runtime,
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-v",
            f"{repo.resolve()}:{CONTAINER_REPO}:ro",
            "-v",
            f"{out_dir.resolve()}:{CONTAINER_OUT}:rw",
            self.image,
            "bash",
            "-c",
            self._script(lint, coverage),
        ]

    def run(
        self,
        repo: Path | str,
        *,
        task_id: str,
        phase: Phase = "post",
        run_id: str | None = None,
        lint: bool = True,
        coverage: bool = False,
    ) -> dict[str, Any]:
        """Verify ``repo`` in a container; return a ``mra:test_report`` dict.

        Writes ``runs/<run_id>/test_report.json`` alongside the raw artifacts
        (NFR-13). Never raises on a failing or timing-out suite — a bad repo is
        a result to report, not an exception to propagate.
        """
        repo = Path(repo)
        run_id = run_id or uuid.uuid4().hex[:12]
        out_dir = self.runs_dir / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # Every run of one run_id shares this directory. A suite killed by the
        # timeout writes no report, so a leftover from the previous run (say,
        # the green pre-migration suite) would be read as this run's result.
        for stale in ("pytest_raw.json", "ruff.json", "coverage.json"):
            (out_dir / stale).unlink(missing_ok=True)
        # Unique per invocation, not per run id: two runs with one id in different
        # runs dirs (or two test workers) never collide on the daemon's name space,
        # and a container an interrupt left behind cannot block the id (BUG-19).
        name = f"mra-{run_id}-{uuid.uuid4().hex[:6]}"
        argv = self._docker_argv(repo, out_dir, name, lint, coverage)
        timed_out = False
        finished = False
        try:
            try:
                completed = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s + HOST_TIMEOUT_GRACE_SEC,
                    check=False,
                )
                # 124 is `timeout`'s own exit code: pytest was killed inside the box.
                timed_out = completed.returncode == 124
                stderr = completed.stderr
            except subprocess.TimeoutExpired as exc:
                # The runtime itself wedged; stop the container so it cannot outlive us.
                subprocess.run([self.runtime, "kill", name], capture_output=True, check=False)
                timed_out = True
                stderr = str(exc)
            finished = True
        finally:
            if not finished:
                # Interrupted (Ctrl+C) while the client launched the box: --rm only
                # covers a container that started, so one left "Created" would block
                # this run id forever (BUG-18). Remove it by name.
                subprocess.run([self.runtime, "rm", "-f", name], capture_output=True, check=False)

        report = self._normalize(
            raw_path=out_dir / "pytest_raw.json",
            ruff_path=out_dir / "ruff.json",
            task_id=task_id,
            phase=phase,
            timed_out=timed_out,
            stderr=stderr,
            lint=lint,
        )
        (out_dir / "test_report.json").write_text(json.dumps(report, indent=2) + "\n")
        return report

    def _normalize(
        self,
        *,
        raw_path: Path,
        ruff_path: Path,
        task_id: str,
        phase: Phase,
        timed_out: bool,
        stderr: str,
        lint: bool,
    ) -> dict[str, Any]:
        """Raw pytest-json-report (or its absence) -> the mra:test_report contract."""
        try:
            raw = json.loads(raw_path.read_text())
        except (OSError, json.JSONDecodeError):
            raw = None

        if raw is None:
            # No report at all: the suite was killed, or the container never ran.
            reason = (
                "pytest exceeded the sandbox timeout"
                if timed_out
                else (
                    stderr.strip().splitlines()[-1]
                    if stderr.strip()
                    else "no pytest report produced"
                )
            )
            exc_type = "Timeout" if timed_out else "SandboxError"
            report: dict[str, Any] = {
                "task_id": task_id,
                "phase": phase,
                "total": 0,
                "passed": 0,
                "failed": 0,
                "errors": 1,
                "skipped": 0,
                "failures": [
                    {
                        "nodeid": "<sandbox>",
                        "signature": failure_signature("<sandbox>", exc_type, reason),
                        "exc_type": exc_type,
                        "message": reason,
                        "trace": stderr[-TRACE_MAX_CHARS:],
                        "file": "",
                        "line": 0,
                    }
                ],
                "duration_s": 0.0,
            }
            if lint:
                report["lint"] = _lint_counts(ruff_path)
            return report

        summary = raw.get("summary", {})
        bad_collectors = [
            c for c in raw.get("collectors", []) if c.get("outcome") not in (None, "passed")
        ]
        failures = [
            _failure_from_test(t)
            for t in raw.get("tests", [])
            if t.get("outcome") not in ("passed", "skipped", "xfailed", "xpassed")
        ] + [_failure_from_collector(c) for c in bad_collectors]

        report = {
            "task_id": task_id,
            "phase": phase,
            "total": int(summary.get("total", 0)),
            "passed": int(summary.get("passed", 0)),
            "failed": int(summary.get("failed", 0)),
            # Collection errors never reach `summary`, so add them in explicitly.
            "errors": int(summary.get("error", 0)) + len(bad_collectors),
            "skipped": int(summary.get("skipped", 0)),
            "failures": failures,
            "duration_s": float(raw.get("duration", 0.0)),
        }
        if lint:
            report["lint"] = _lint_counts(ruff_path)
        return report
