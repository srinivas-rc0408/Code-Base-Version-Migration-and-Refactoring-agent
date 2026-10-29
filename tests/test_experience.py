"""Feature D: the opt-in experience store.

Off by default, never touched by the benchmark, nothing written when off,
one-command purge, retrieval by failure class + contract, and no path that
could name a repository in what it stores.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from mra.benchmark.runner import CONFIGS, TASKS, codemod_corrector, replay, run_one, warm_store
from mra.cli import main as cli
from mra.memory.experience import ExperienceStore, format_hint, from_config
from mra.nodes.correct_node import patch_prompt
from tests.conftest import unique_id

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK03 = REPO_ROOT / "corpus" / "tierA" / "task03_half_migration"
CONTRACT = {"source_api": "datetime.utcnow", "target_api": "datetime.now(timezone.utc)"}
MESSAGE = "TypeError: can't subtract offset-naive and offset-aware datetimes"
DIFF = """\
diff --git a/src/pkg/report.py b/src/pkg/report.py
--- a/src/pkg/report.py
+++ b/src/pkg/report.py
@@ -1,4 +1,4 @@
-from datetime import datetime
+from datetime import datetime, timezone
-    return datetime.utcnow()
+    return datetime.now(timezone.utc)
"""

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="needs a working Docker daemon",
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("MRA_EXPERIENCE", raising=False)
    monkeypatch.setenv("MRA_EXPERIENCE_DB", str(tmp_path / "experience.db"))
    return tmp_path / "experience.db"


def test_off_by_default(db: Path) -> None:
    assert from_config({}) is None
    assert from_config({"experience": {"enabled": False}}) is None


def test_env_off_beats_config_on(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRA_EXPERIENCE", "off")
    assert from_config({"experience": {"enabled": True}}) is None
    monkeypatch.setenv("MRA_EXPERIENCE", "on")
    assert from_config({}) is not None


def test_store_inside_a_repo_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside every repository"):
        ExperienceStore(REPO_ROOT / "experience.db")
    with pytest.raises(ValueError):
        ExperienceStore(tmp_path / "repo" / "x.db", forbidden=(tmp_path / "repo",))


def test_retrieval_returns_the_stored_fix_for_a_matching_failure(db: Path) -> None:
    store = ExperienceStore(db)
    assert store.record("behaviour", MESSAGE, CONTRACT, DIFF)
    assert not store.record("behaviour", MESSAGE, CONTRACT, DIFF)  # deduplicated

    hits = store.hints("behaviour", MESSAGE + " (again)", CONTRACT)
    assert len(hits) == 1 and "datetime.now(timezone.utc)" in hits[0]["pattern"]
    assert store.hints("import", MESSAGE, CONTRACT) == []
    assert store.hints("behaviour", MESSAGE, {**CONTRACT, "target_api": "other"}) == []

    prompt = patch_prompt(
        {"nodeid": "t", "message": MESSAGE},
        {"file": "a.py", "importers": [], "imports": [], "sites": [], "source": "x = 1\n"},
        CONTRACT,
        "behaviour",
        hints=[format_hint(h) for h in hits],
    )
    assert "past fixes for similar failures" in prompt and hits[0]["pattern"] in prompt


def test_hints_stay_within_budget(db: Path) -> None:
    store = ExperienceStore(db)
    for n in range(10):
        store.record(
            "behaviour", f"{MESSAGE} {'x' * n}", CONTRACT, "-a = 1\n+" + "b" * 600 + f"{n}\n"
        )
    from mra.memory.experience import HINT_BUDGET_CHARS

    hits = store.hints("behaviour", MESSAGE, CONTRACT)
    assert hits and sum(len(format_hint(h)) for h in hits) <= HINT_BUDGET_CHARS


def test_paths_and_secrets_are_stripped_before_storage(db: Path) -> None:
    store = ExperienceStore(db)
    store.record(
        "import",
        "ImportError: cannot import name 'x' from 'pkg.mod' "
        "(/home/alice/work/acme-repo/src/pkg/mod.py) key sk-abcdefghijklmnopqrstuv",
        CONTRACT,
        "-open(\"/home/alice/work/acme-repo/data.csv\")\n+open('x')\n"
        '-token = "sk-abcdefghijklmnopqrstuvwxyz"\n+token = None\n',
    )
    row = repr(store.rows())
    assert "/home/alice" not in row and "acme-repo" not in row and "mod.py" not in row
    assert "sk-abcdefghij" not in row


def test_purge_is_one_command(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = ExperienceStore(db)
    store.record("behaviour", MESSAGE, CONTRACT, DIFF)
    assert cli(["memory", "stats"]) == 0 and '"fixes": 1' in capsys.readouterr().out
    assert cli(["memory", "purge"]) == 0
    assert store.rows() == [] and store.stats()["fixes"] == 0
    assert cli(["memory", "export"]) == 0 and '"fixes": []' in capsys.readouterr().out


def test_readonly_store_learns_nothing(db: Path) -> None:
    assert not ExperienceStore(db, readonly=True).record("behaviour", MESSAGE, CONTRACT, DIFF)
    assert not db.exists()


def test_replay_applies_a_learnt_pattern() -> None:
    source = "from datetime import datetime\n\n\ndef f():\n    x = datetime.utcnow()\n"
    out = replay(
        "-from datetime import datetime\n+from datetime import datetime, timezone\n"
        "-    return datetime.utcnow()\n+    return datetime.now(timezone.utc)",
        source,
    )
    assert out == (
        "from datetime import datetime, timezone\n\n\ndef f():\n"
        "    x = datetime.now(timezone.utc)\n"
    )


def test_training_split_refuses_evaluation_tasks(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path / "x.db")
    with pytest.raises(ValueError, match="leakage"):
        warm_store(store, [TASK03], tmp_path / "runs")
    assert TASK03.name in TASKS


@needs_docker
def test_learns_a_green_correction_and_stores_no_repo_path(db: Path, tmp_path: Path) -> None:
    from mra.report import run_with_report

    store = ExperienceStore(db)
    result = run_with_report(
        TASK03,
        run_id=unique_id("learn"),
        runs_dir=tmp_path / "runs",
        corrector=codemod_corrector,
        experience=store,
    )
    assert result["model"]["verdict"]["status"] == "GREEN" and result["experience_learned"] >= 1
    rows = store.rows()
    repo = result["out_dir"] / "repo"
    files = [p.relative_to(repo).as_posix() for p in repo.rglob("*.py")]
    for row in rows:
        text = repr(row)
        assert str(tmp_path) not in text and "/home/" not in text
        assert not any(name in text for name in files)
    assert store.hints(rows[0]["failure_class"], rows[0]["message"], CONTRACT)


@needs_docker
def test_nothing_written_when_off(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MRA_EXPERIENCE", "off")
    assert cli(["run", "--task-dir", str(TASK03), "--runs-dir", str(tmp_path)]) == 0
    assert not db.exists()


@needs_docker
def test_forced_off_in_the_benchmark(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MRA_EXPERIENCE", "on")  # the user's config says on ...
    baseline = next(c for c in CONFIGS if c.name == "baseline")
    row = run_one(TASK03, baseline, runs_dir=tmp_path)
    assert row["corrections"] >= 1  # ... a CORRECT turned the suite green ...
    assert not db.exists()  # ... and the benchmark still wrote nothing.
    with pytest.raises(ValueError, match="read-only"):
        run_one(
            TASK03,
            next(c for c in CONFIGS if c.name == "memory-warm"),
            runs_dir=tmp_path,
            experience=ExperienceStore(db),
        )


def test_rows_table_has_no_path_column(db: Path) -> None:
    ExperienceStore(db).record("behaviour", MESSAGE, CONTRACT, DIFF)
    columns = [c[1] for c in sqlite3.connect(db).execute("PRAGMA table_info(fixes)")]
    assert not any("path" in c or "file" in c or "repo" in c for c in columns)


@needs_docker
def test_forced_off_in_the_edge_runner(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mra.benchmark.edge import run_case

    monkeypatch.setenv("MRA_EXPERIENCE", "on")
    # The edge runner names the run after the case directory; a uniquely named copy
    # keeps this run's container apart from test_edge's run of the same case.
    case = tmp_path / unique_id("cross_file_recovery")
    shutil.copytree(REPO_ROOT / "corpus" / "edge" / "cross_file_recovery", case)
    row = run_case(case, tmp_path / "runs")
    assert row["pass"], row["problems"]  # the case needs a CORRECT to reach GREEN ...
    assert not db.exists()  # ... and still nothing was learnt.
