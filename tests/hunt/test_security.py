"""Hunt 6 — what leaves the repo boundary, and what lands in prompts and reports.

* A symlink inside the repo pointing outside it must not pull the outside
  file into the run (copy, edit, patch, report, prompt).
* A fake API key in a source file must never appear in a prompt sent to a
  remote endpoint, nor in any log, trajectory or report.
* ``.env`` contents must never reach a prompt or an artifact.

Markers are unique fake strings; nothing here is a real credential.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfReader

from mra.analysis import call_sites as call_sites_module
from mra.benchmark.runner import codemod_corrector
from mra.codemods.datetime_utcnow import TARGET, family
from mra.models import ROLES, Endpoint, Router
from mra.models.providers import FakeProvider
from mra.nodes.correct_node import LLMCorrector
from mra.nodes.edit_node import apply_codemod
from mra.report import run_with_report
from tests.hunt.conftest import TIER_A, bug, needs_docker
from tests.hunt.test_hostile_replies import CONTRACT, GOLD_REPORT, RESIDUAL_FAILURE, _fence

OUTSIDE_MARKER = "HUNT_OUTSIDE_7f3a9c"
ENV_MARKER = "HUNT_ENV_SECRET_b81d0e"


def run_artifacts(out_dir: Path) -> dict[str, str]:
    """Every log/trajectory/report artifact of a run, as text (repo/ and verify/ excluded)."""
    texts = {}
    for path in sorted(out_dir.rglob("*")):
        rel = path.relative_to(out_dir)
        if not path.is_file() or rel.parts[0] in ("repo", "verify"):
            continue
        if path.suffix == ".pdf":
            texts[str(rel)] = "\n".join(p.extract_text() for p in PdfReader(path).pages)
        else:
            texts[str(rel)] = path.read_bytes().decode("utf-8", errors="replace")
    return texts


def _leaks(texts: dict[str, str], marker: str) -> list[str]:
    return sorted(name for name, text in texts.items() if marker in text)


# -- symlink pointing outside the repo -----------------------------------------------


def _task_with_symlink(tmp_path: Path, kind: str) -> tuple[Path, Path]:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "shared.py"
    secret.write_text(
        f'"""{OUTSIDE_MARKER}: private module outside the repo."""\n\n'
        "from datetime import datetime\n\n\n"
        "def private_stamp():\n    return datetime.utcnow()\n"
    )
    task = tmp_path / "task01_datetime"
    shutil.copytree(TIER_A / "task01_datetime", task)
    link = task / "old" / "src" / "pkg" / ("shared.py" if kind == "file" else "vendored")
    link.symlink_to(secret if kind == "file" else outside)
    return task, secret


@needs_docker
@pytest.mark.parametrize(
    "kind",
    ["file", "dir"],
)
def test_symlink_outside_repo_is_not_followed(tmp_path: Path, kind: str) -> None:
    task, secret = _task_with_symlink(tmp_path, kind)
    before = secret.read_bytes()
    result = run_with_report(
        task, run_id="sym", runs_dir=tmp_path / "runs", corrector=codemod_corrector
    )
    assert secret.read_bytes() == before, "the file outside the repo was modified"
    leaks = _leaks(run_artifacts(result["out_dir"]), OUTSIDE_MARKER)
    patch = (result["out_dir"] / "migration.patch").read_text()
    assert not leaks and OUTSIDE_MARKER not in patch, f"outside content in {leaks}"
    copied = list((result["out_dir"] / "repo").rglob("*shared.py"))
    assert not copied, f"outside file copied into the run: {copied}"


@bug("BUG-15", "find_in_repo/apply_codemod follow a symlinked file and write through it")
def test_codemod_on_a_symlinked_file_does_not_write_outside(tmp_path: Path) -> None:
    """find_in_repo/apply_codemod are also used directly (locate, reversal, the CLI scan)."""
    task, secret = _task_with_symlink(tmp_path, "file")
    repo = task / "old"
    before = secret.read_bytes()
    apply_codemod(repo, call_sites_module.find_in_repo(repo, family(TARGET)))
    assert secret.read_bytes() == before, "apply_codemod wrote through a symlink outside the repo"


# -- fake API keys in a source file ----------------------------------------------------

KEYS = {
    "openai_sk": ('OPENAI_KEY = "sk-proj-{m}0123456789abcdefABCD"', None),
    "nvidia_assignment": ('NVIDIA_API_KEY = "nvapi-{m}0123456789abcdefABCDEF"', None),
    "bearer_header": (
        'HEADERS = {{"Authorization": "Bearer nvapi-{m}0123456789abcdef"}}',
        None,
    ),
    "dict_api_key": ('CONFIG = {{"api_key": "{m}0123456789abcdef"}}', None),
    "stripe_live": ('PAYMENTS = "sk_live_{m}0123456789abcdefgh"', None),
    "huggingface": ('HUB = "hf_{m}abcdefghijklmnopqrstuvwxyz"', None),
    "url_password": ('DB_URL = "postgres://app:{m}pw@db.internal/prod"', None),
    "anthropic": ('CLAUDE = "sk-ant-api03-{m}0123456789abcdef"', None),
    "aws_secret": ('aws_secret_access_key = "{m}/0123456789abcdefABCDEF"', None),
}


def _key_case(name: str) -> Any:
    marker = f"HUNTKEY{name.upper().replace('_', '')}"
    line, bug_id = KEYS[name]
    marks = [bug(bug_id, f"redaction misses the {name} key shape")] if bug_id else []
    return pytest.param(line.format(m=marker), marker, marks=marks, id=name)


@pytest.mark.parametrize(("line", "marker"), [_key_case(n) for n in KEYS])
def test_fake_key_never_reaches_a_remote_prompt(tmp_path: Path, line: str, marker: str) -> None:
    work = tmp_path / "repo"
    shutil.copytree(TIER_A / "task03_half_migration" / "old", work)
    sites = call_sites_module.find_in_repo(work, family(TARGET))
    apply_codemod(work, {f: s for f, s in sites.items() if f != "src/pkg/report.py"})
    report = work / "src" / "pkg" / "report.py"
    report.write_text(report.read_text() + f"\n{line}\n")
    (work / ".env").write_text(f"SERVICE_TOKEN={ENV_MARKER}\n")
    # The key also shows up in the failure, as a failing assertion would print it.
    failure = {**RESIDUAL_FAILURE, "message": f"AssertionError: assert {line}"}

    sent: list[str] = []

    def reply(messages: list[dict[str, str]], model: str) -> str:
        sent.extend(m["content"] for m in messages)
        return "behaviour" if "one word" in messages[0]["content"] else _fence(GOLD_REPORT, None)

    remote = FakeProvider("remote", reply=reply, base_url="https://api.example.invalid/v1")
    router = Router(roles={r: [Endpoint(remote, "m")] for r in ROLES})
    LLMCorrector(router, TARGET, CONTRACT)(work, failure, {})
    prompts = "\n".join(sent)
    assert sent, "control: the model was asked"
    assert ENV_MARKER not in prompts, ".env contents reached a prompt"
    assert marker not in prompts, f"key reached a remote prompt: {line}"


@needs_docker
@bug(
    "BUG-13",
    "secrets next to an edited line are copied into report.json and the PDF "
    "(diff excerpts are not redacted)",
)
def test_fake_key_never_reaches_a_report(tmp_path: Path) -> None:
    marker = "sk-HUNTREPORT0123456789abcdefABCD"
    task = tmp_path / "task01_datetime"
    shutil.copytree(TIER_A / "task01_datetime", task)
    core = task / "old" / "src" / "pkg" / "core.py"
    lines = core.read_text().splitlines()
    at = next(i for i, text in enumerate(lines) if "utcnow" in text)
    lines.insert(at, f'    _token = "{marker}"  # next to the edit, so it is diff context')
    core.write_text("\n".join(lines) + "\n")
    (task / "old" / ".env").write_text(f"SERVICE_TOKEN={ENV_MARKER}\n")
    result = run_with_report(
        task, run_id="keys", runs_dir=tmp_path / "runs", corrector=codemod_corrector
    )
    assert result["model"]["verdict"]["status"] in ("GREEN", "YELLOW")
    texts = run_artifacts(result["out_dir"])
    assert not _leaks(texts, ENV_MARKER), f".env in {_leaks(texts, ENV_MARKER)}"
    leaks = [n for n in _leaks(texts, marker) if n != "migration.patch"]
    assert not leaks, f"key in {leaks}"
