"""Hunt 4 — environment faults: the run must end in a clean, honest RED, never a
traceback, a misleading verdict, or another run's artifacts.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from mra.benchmark.runner import codemod_corrector
from mra.report import run_with_report
from tests.hunt.conftest import ROOT, TIER_A, bug, needs_docker

EDGE = ROOT / "corpus" / "edge"


def _run(task_dir: Path, runs: Path, run_id: str = "r") -> dict[str, Any]:
    return run_with_report(task_dir, run_id=run_id, runs_dir=runs, corrector=codemod_corrector)


def _codes(result: dict[str, Any]) -> set[str]:
    return {r["code"] for r in result["model"]["issues"]}


def _cli(
    *args: str, env: dict[str, str] | None = None, cwd: Path | None = None, **kw: Any
) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "mra.cli", *args],
        cwd=cwd or ROOT,
        env={**os.environ, "NO_COLOR": "1", **(env or {})},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **kw,
    )


# -- the sandbox is unavailable ------------------------------------------------------


@bug("BUG-08", "docker daemon down is reported as 'your pre-migration suite is not green'")
def test_docker_daemon_stopped_is_named_as_such(tmp_path: Path, monkeypatch: Any) -> None:
    fake = tmp_path / "docker"
    fake.write_text(
        "#!/bin/sh\necho 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
        "Is the docker daemon running?' >&2\nexit 125\n"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("MRA_CONTAINER_RUNTIME", str(fake))
    result = _run(TIER_A / "task01_datetime", tmp_path / "runs")
    assert result["model"]["verdict"]["status"] == "RED"
    text = json.dumps(result["model"]["verdict"]["reasons"])
    assert "daemon" in text.lower() or "docker" in text.lower(), (
        f"the verdict never says the sandbox is down: {_codes(result)}"
    )
    assert "precondition" not in _codes(result), "blames the user's test suite"


def test_container_runtime_missing_is_a_red_report(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("MRA_CONTAINER_RUNTIME", str(tmp_path / "no-such-docker"))
    result = _run(TIER_A / "task01_datetime", tmp_path / "runs")
    assert result["model"]["verdict"]["status"] == "RED"
    assert result["pdf"].is_file()


# -- bad inputs -----------------------------------------------------------------------


def test_missing_repo_path_is_a_clean_red(tmp_path: Path) -> None:
    proc = _cli(
        "run", "--task-dir", str(tmp_path / "does not exist"), "--runs-dir", str(tmp_path / "runs")
    )
    out, err = proc.communicate(timeout=300)
    assert proc.returncode == 2, (out, err)
    assert "Traceback" not in err, err[-1500:]
    assert "[RED]" in out


@needs_docker
def test_repo_with_no_tests_is_refused(tmp_path: Path) -> None:
    result = _run(EDGE / "zero_tests", tmp_path / "runs")
    assert result["model"]["verdict"]["status"] == "RED"
    assert "precondition" in _codes(result)
    patch = result["out_dir"] / "migration.patch"
    assert not patch.exists() or not patch.read_text().strip(), "a refused run edited code"


@needs_docker
def test_task_that_is_not_a_git_repo(tmp_path: Path) -> None:
    """The normal case (corpus dirs are plain trees) — also the control for the next test."""
    result = _run(TIER_A / "task01_datetime", tmp_path / "runs")
    assert result["model"]["verdict"]["status"] == "GREEN", _codes(result)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=u", "-c", "user.email=u@x", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@needs_docker
def test_repo_that_already_is_a_git_repo(tmp_path: Path) -> None:
    task = tmp_path / "task01_datetime"
    shutil.copytree(TIER_A / "task01_datetime", task)
    old = task / "old"
    core = old / "src" / "pkg" / "core.py"
    original = core.read_text()
    core.write_text("# an older revision\n" + original)
    _git(old, "init", "-q")
    _git(old, "add", "-A")
    _git(old, "commit", "-qm", "user's first commit")
    core.write_text(original)  # the working tree is newer than the user's root commit
    _git(old, "commit", "-qam", "user's second commit")

    base = _run(TIER_A / "task01_datetime", tmp_path / "base_runs", "base")
    result = _run(task, tmp_path / "runs")
    assert result["model"]["verdict"]["status"] == "GREEN", sorted(_codes(result))
    patch = (result["out_dir"] / "migration.patch").read_text()
    assert patch == (base["out_dir"] / "migration.patch").read_text()


@bug("BUG-14", "read-only --runs-dir: PermissionError raised from the report's finally block")
def test_read_only_output_dir_fails_cleanly(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    runs.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        proc = _cli("run", "--task-dir", str(TIER_A / "task01_datetime"), "--runs-dir", str(runs))
        out, err = proc.communicate(timeout=300)
    finally:
        runs.chmod(0o755)
    assert proc.returncode != 0
    assert "Traceback" not in err, f"bare traceback instead of an error message:\n{err[-1200:]}"


# -- concurrency ------------------------------------------------------------------------


@needs_docker
def test_two_runs_with_distinct_ids_at_once(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    procs = [
        _cli("run", "--task-dir", str(TIER_A / task), "--runs-dir", str(runs), "--run-id", rid)
        for task, rid in (("task01_datetime", "one"), ("task04_multimodule", "two"))
    ]
    outs = [p.communicate(timeout=900) for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
    for rid, task in (("one", "task01_datetime"), ("two", "task04_multimodule")):
        meta = json.loads((runs / rid / "run_meta.json").read_text())
        assert meta["task_id"] == task


def test_two_runs_with_the_same_id_at_once(tmp_path: Path) -> None:
    """BUG-10: while a live run holds an id, `mra run` with it refuses and touches nothing.

    The id is held by this process exactly as a live run holds it, so the overlap is
    certain; timing two real runs 3 s apart stopped overlapping once a run took < 3 s.
    """
    from mra.report import run_lock

    runs = tmp_path / "runs"
    marker = runs / "same" / "marker"
    marker.parent.mkdir(parents=True)
    marker.write_text("the live run's")
    with run_lock(runs, "same"):
        proc = _cli(
            "run",
            "--task-dir",
            str(TIER_A / "task04_multimodule"),
            "--runs-dir",
            str(runs),
            "--run-id",
            "same",
        )
        out, err = proc.communicate(timeout=120)
    assert proc.returncode == 2, (out, err)
    assert "in use by another live run" in out
    assert "Traceback" not in err
    assert marker.read_text() == "the live run's"
    assert sorted(p.name for p in (runs / "same").iterdir()) == ["marker"]


#: A real run that hangs inside run_with_report's locked region until it is killed.
HANG = """
import sys, time
from mra.report import run_with_report

def hang(run_id):
    print("running", flush=True)
    time.sleep(600)

run_with_report(sys.argv[1], run_id="same", runs_dir=sys.argv[2], setup=hang)
"""


def test_a_killed_run_does_not_block_its_run_id(tmp_path: Path) -> None:
    """BUG-10: the run-id lock is an OS flock, so it dies with the process holding it."""
    from mra.models import PrivacyError
    from mra.report import RunBusy

    runs, task = tmp_path / "runs", TIER_A / "task01_datetime"
    child = subprocess.Popen(
        [sys.executable, "-c", HANG, str(task), str(runs)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline() == "running\n"
        marker = runs / "same" / "marker"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("the live run's")
        with pytest.raises(RunBusy, match="same"):
            run_with_report(task, run_id="same", runs_dir=runs)
        assert marker.read_text() == "the live run's", "a refused run touched nothing"
    finally:
        child.send_signal(signal.SIGKILL)
        child.wait()

    assert (runs / "same.lock").exists(), "the file outlives the process; the lock does not"

    def refuse(run_id: str) -> dict[str, Any]:
        raise PrivacyError("stop before the sandbox")

    result = run_with_report(task, run_id="same", runs_dir=runs, setup=refuse)
    assert result["model"]["meta"]["run_id"] == "same"
    assert not marker.exists(), "the fresh run owns its directory"


# -- Ctrl+C mid-batch ----------------------------------------------------------------------


def test_interrupt_removes_the_named_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic: the interrupt lands while the runtime client is starting the box."""
    from mra.sandbox import SandboxRunner

    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        calls.append(list(argv))
        if argv[1] == "run":
            raise KeyboardInterrupt
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("mra.sandbox.runner.subprocess.run", fake_run)
    runner = SandboxRunner(runs_dir=tmp_path, runtime="docker")
    with pytest.raises(KeyboardInterrupt):
        runner.run(TIER_A / "task01_datetime" / "old", task_id="t", run_id="intr2")
    [started] = [argv for argv in calls if argv[1] == "run"]
    name = started[started.index("--name") + 1]
    assert name.startswith("mra-intr2-")
    assert ["docker", "rm", "-f", name] in calls, calls


@needs_docker
def test_ctrl_c_mid_batch(tmp_path: Path) -> None:
    """SIGINT to the process group (what a terminal sends) once batch 1 has started."""
    runs = tmp_path / "runs"
    proc = _cli(
        "run",
        "--task-dir",
        str(TIER_A / "task04_multimodule"),
        "--runs-dir",
        str(runs),
        "--run-id",
        "intr",
        env={"MRA_EDIT_BATCH_SIZE": "1"},
        start_new_session=True,
    )
    repo = runs / "intr" / "repo"
    deadline = time.time() + 300
    while time.time() < deadline:
        if (repo / ".git").is_dir():
            log = subprocess.run(
                ["git", "log", "--format=%s"], cwd=repo, capture_output=True, text=True
            ).stdout
            if "pre-edit snapshot for batch 1" in log:
                break
        time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("never reached batch 1")
    os.killpg(proc.pid, signal.SIGINT)
    out, err = proc.communicate(timeout=600)

    out_dir = runs / "intr"
    leftovers = subprocess.run(  # -a: a container stuck in "Created" counts (BUG-18)
        ["docker", "ps", "-a", "-q", "--filter", "name=^mra-intr$"], capture_output=True, text=True
    ).stdout.split()
    assert not leftovers, f"containers outlived the run: {leftovers}"
    assert (out_dir / "run_meta.json").is_file(), "no run_meta.json after Ctrl+C"
    assert (out_dir / "report.json").is_file(), f"no report after Ctrl+C:\n{err[-1500:]}"
    report = json.loads((out_dir / "report.json").read_text())
    assert report["verdict"]["status"] == "RED"
    # No half-applied edit: every file the patch touches is fully migrated.
    from mra.analysis.call_sites import find_in_repo
    from mra.codemods.datetime_utcnow import TARGETS
    from mra.report.evidence import parse_patch

    patched = parse_patch((out_dir / "migration.patch").read_text())
    residual = find_in_repo(repo, TARGETS)
    assert not set(patched) & set(residual), f"half-migrated files: {set(patched) & set(residual)}"
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "corpus"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    assert not dirty.strip(), f"corpus source was modified: {dirty}"
