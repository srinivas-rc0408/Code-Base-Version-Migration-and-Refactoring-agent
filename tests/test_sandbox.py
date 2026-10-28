"""P0 acceptance: the sandbox verifies a real corpus task and reports it as data.

These are integration tests — they build nothing but they do run containers, and
they run against `corpus/tierA/task01_datetime`, not a fixture invented here. A
verifier that only works on toy input is not a verifier.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest

from mra.sandbox import SandboxRunner, failure_signature, normalize_message

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK01_OLD = REPO_ROOT / "corpus" / "tierA" / "task01_datetime" / "old"
SRS = REPO_ROOT / "docs" / "03_SRS.md"

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="needs a working Docker daemon",
)


@pytest.fixture(scope="session")
def test_report_schema() -> dict:
    """Pull the mra:test_report schema out of the SRS itself.

    Golden rule 4 makes the SRS the authoritative shape, so the test reads it
    from the document rather than keeping a second copy that can silently drift.
    """
    blocks = re.findall(r"```json\n(.*?)\n```", SRS.read_text(), re.S)
    for block in blocks:
        if '"$id": "mra:test_report"' in block:
            return json.loads(block)
    pytest.fail("mra:test_report schema not found in docs/03_SRS.md")


@pytest.fixture(scope="session")
def runner(tmp_path_factory: pytest.TempPathFactory) -> SandboxRunner:
    return SandboxRunner(runs_dir=tmp_path_factory.mktemp("runs"))


@pytest.fixture(scope="session")
def green_report(runner: SandboxRunner) -> dict:
    return runner.run(TASK01_OLD, task_id="task01_datetime", phase="pre")


def _tree_digest(root: Path) -> str:
    """Content hash of every file under ``root``, for tamper detection."""
    sha = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        sha.update(str(path.relative_to(root)).encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()


def _break_copy(source: Path, destination: Path) -> Path:
    """Copy a task tree and inject one failing assertion into its suite."""
    shutil.copytree(source, destination)
    (destination / "tests" / "test_core.py").open("a").write(
        "\n\ndef test_injected_failure() -> None:\n    assert make_timestamp().year == 1999\n"
    )
    return destination


@needs_docker
def test_green_report_matches_the_srs_schema(green_report: dict, test_report_schema: dict) -> None:
    jsonschema.validate(green_report, test_report_schema)


@needs_docker
def test_passing_task_reports_all_green(green_report: dict) -> None:
    assert green_report["total"] == 5
    assert green_report["passed"] == green_report["total"]
    assert green_report["failed"] == 0
    assert green_report["errors"] == 0
    assert green_report["failures"] == []


@needs_docker
def test_deprecation_warnings_do_not_count_as_failures(green_report: dict) -> None:
    """task01/old raises DeprecationWarning on every utcnow() call and is still green."""
    assert green_report["passed"] == 5
    assert green_report["failed"] == 0


@needs_docker
def test_failing_task_reports_a_usable_failure(
    runner: SandboxRunner, tmp_path: Path, test_report_schema: dict
) -> None:
    broken = _break_copy(TASK01_OLD, tmp_path / "broken")
    report = runner.run(broken, task_id="task01_datetime", phase="post")

    jsonschema.validate(report, test_report_schema)
    assert report["failed"] > 0
    failure = report["failures"][0]
    assert failure["signature"]
    assert failure["exc_type"] == "AssertionError"
    assert failure["trace"]
    assert failure["nodeid"].endswith("::test_injected_failure")
    assert failure["file"] == "tests/test_core.py"


@needs_docker
def test_input_mount_is_not_modified(runner: SandboxRunner) -> None:
    """The source tree is mounted :ro and copied inside; a run must not touch it.

    The digest brackets the run, so this catches both an edit and a stray
    .pytest_cache/ or egg-info written into the operator's own corpus.
    """
    before = _tree_digest(TASK01_OLD)
    runner.run(TASK01_OLD, task_id="task01_datetime", phase="pre", lint=False)
    assert _tree_digest(TASK01_OLD) == before


@needs_docker
def test_same_failure_yields_the_same_signature(runner: SandboxRunner, tmp_path: Path) -> None:
    """Retry capping (NFR-1) is meaningless if a signature drifts between runs.

    The injected assertion embeds the current clock in its own message, so this
    only holds because the signature normalizes volatile text away.
    """
    broken = _break_copy(TASK01_OLD, tmp_path / "broken_twice")
    first = runner.run(broken, task_id="task01_datetime", phase="post", lint=False)
    second = runner.run(broken, task_id="task01_datetime", phase="recovery", lint=False)
    assert first["failures"][0]["signature"] == second["failures"][0]["signature"]


def test_normalization_strips_volatile_text() -> None:
    a = "assert 2026 == 1999 + where datetime(2026, 9, 20) at 0xdeadbeef in /work/repo_rw/x.py"
    b = "assert 2025 == 1999 + where datetime(2025, 1, 2) at 0xcafe in /work/repo_rw/x.py"
    assert normalize_message(a) == normalize_message(b)


def test_different_failures_get_different_signatures() -> None:
    same = failure_signature("t.py::a", "AssertionError", "assert 1 == 2")
    other_node = failure_signature("t.py::b", "AssertionError", "assert 1 == 2")
    other_type = failure_signature("t.py::a", "TypeError", "assert 1 == 2")
    assert len({same, other_node, other_type}) == 3


def test_snapshot_rollback_and_diff_round_trip(tmp_path: Path) -> None:
    """Snapshot before a batch, mutate, roll back: NFR-9 in one pass."""
    from mra.sandbox import diff, rollback, snapshot

    work = tmp_path / "work"
    shutil.copytree(TASK01_OLD, work)
    base = snapshot(work, "before batch 0")

    core = work / "src" / "pkg" / "core.py"
    core.write_text(core.read_text().replace("utcnow()", "now(timezone.utc)"))
    patch = diff(work)
    assert "-    return datetime.utcnow()" in patch
    assert "+    return datetime.now(timezone.utc)" in patch

    rollback(work, base)
    assert "utcnow()" in core.read_text()
    assert diff(work) == ""


@needs_docker
def test_timeout_returns_a_structured_report(runner: SandboxRunner, tmp_path: Path) -> None:
    """NFR-4: a hanging suite is a reportable result, never an exception."""
    slow = tmp_path / "slow"
    shutil.copytree(TASK01_OLD, slow)
    (slow / "tests" / "test_core.py").open("a").write(
        "\n\ndef test_hangs() -> None:\n    import time\n    time.sleep(120)\n"
    )
    report = SandboxRunner(runs_dir=runner.runs_dir, timeout_s=5).run(
        slow, task_id="task01_datetime", phase="post", lint=False
    )
    assert report["errors"] == 1
    assert report["failures"][0]["exc_type"] == "Timeout"


@needs_docker
def test_unparseable_repo_is_not_reported_as_green(
    runner: SandboxRunner, tmp_path: Path, test_report_schema: dict
) -> None:
    """Collection errors never reach pytest's summary; counting them is on us."""
    broken = tmp_path / "syntax"
    shutil.copytree(TASK01_OLD, broken)
    (broken / "src" / "pkg" / "core.py").open("a").write("\ndef broken(:\n")

    report = runner.run(broken, task_id="task01_datetime", phase="post", lint=False)
    jsonschema.validate(report, test_report_schema)
    assert report["errors"] > 0
    assert report["failures"]
    assert all(f["signature"] for f in report["failures"])


@needs_docker
def test_timeout_after_a_green_run_is_not_read_as_green(
    runner: SandboxRunner,
    tmp_path: Path,
) -> None:
    """A killed suite writes no report: the previous run's green one must not stand in.

    Found by the edge suite (edit_causes_infinite_loop): pre and post share a
    run_id directory, so the post-migration hang was reported as 1/1 passed.
    """
    sandbox = SandboxRunner(runs_dir=runner.runs_dir, timeout_s=5)
    green = sandbox.run(
        TASK01_OLD, task_id="task01_datetime", phase="pre", run_id="stale-check", lint=False
    )
    assert green["failed"] == 0 and green["errors"] == 0
    slow = tmp_path / "slow"
    shutil.copytree(TASK01_OLD, slow)
    (slow / "tests" / "test_core.py").open("a").write(
        "\n\ndef test_hangs() -> None:\n    import time\n    time.sleep(120)\n"
    )
    hung = sandbox.run(
        slow, task_id="task01_datetime", phase="post", run_id="stale-check", lint=False
    )
    assert hung["errors"] == 1 and hung["failures"][0]["exc_type"] == "Timeout"


def test_copy_repo_keeps_inside_links_and_refuses_escaping_ones(tmp_path: Path) -> None:
    from mra.sandbox import UnsafeRepoError, copy_repo

    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "real.py").write_text("x = 1\n")
    (src / "pkg" / "alias.py").symlink_to("real.py")  # relative, stays inside
    copy_repo(src, tmp_path / "ok")
    assert (tmp_path / "ok" / "pkg" / "alias.py").is_symlink()

    (tmp_path / "outside.py").write_text("secret = 1\n")
    for target in (tmp_path / "outside.py", src / "pkg" / "real.py"):  # elsewhere / back into src
        link = src / "pkg" / "link.py"
        link.unlink(missing_ok=True)
        link.symlink_to(target)
        dest = tmp_path / f"bad_{target.name}"
        with pytest.raises(UnsafeRepoError, match="pkg/link.py"):
            copy_repo(src, dest)
        assert not dest.exists(), "the refused copy is removed"
