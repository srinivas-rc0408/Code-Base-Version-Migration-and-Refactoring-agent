"""Hunt 5 — determinism: each Tier-A task three times, offline (codemod corrector).

Patches must be byte-identical; metrics, trajectory, verification evidence,
report.json and the PDF text must be identical once recorded timestamps, run
ids, durations and the commit SHAs derived from them are normalised away.
Anything else that differs is a determinism bug.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfReader

from mra.benchmark.runner import codemod_corrector
from mra.report import run_with_report
from tests.hunt.conftest import TIER_A, needs_docker

REPEATS = 3
#: Keys whose values are recorded clock readings or measured durations.
VOLATILE_KEYS = {
    "ts",
    "started_at",
    "completed_at",
    "completed_tz",
    "wall_clock_s",
    "duration_s",
    "latency_s",
    "generated",
    "generated_at",
    "created_at",
}
SHA = re.compile(r"\b[0-9a-f]{40}\b")
SHORT_SHA = re.compile(r"\b[0-9a-f]{7,12}\b")
CLOCK = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
    r"(\s?[+-]\d{2}:?\d{2}|Z| \S+)?( \([+-]\d{2}:\d{2}\))?"
)
DURATION = re.compile(r"\b\d+(\.\d+)?\s?s\b")
#: The compact minute stamp in the PDF file name, e.g. ``20261028-1045``.
STAMP = re.compile(r"(?<!\d)\d{8}-\d{4}(?!\d)")


def _norm(value: Any, run_id: str) -> Any:
    if isinstance(value, dict):
        return {k: "<t>" if k in VOLATILE_KEYS else _norm(v, run_id) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v, run_id) for v in value]
    if isinstance(value, str):
        value = value.replace(run_id, "<run>").replace(run_id[:8], "<run>")
        value = SHA.sub("<sha>", value)
        return CLOCK.sub("<clock>", value)
    return value


def _text(value: str, run_id: str) -> str:
    value = value.replace(run_id, "<run>").replace(run_id[:8], "<run>")
    value = SHA.sub("<sha>", CLOCK.sub("<clock>", STAMP.sub("<clock>", value)))
    return DURATION.sub("<dur>", SHORT_SHA.sub("<sha>", value))


def _snapshot(out_dir: Path, run_id: str) -> dict[str, Any]:
    def load(name: str) -> Any:
        path = out_dir / name
        return _norm(json.loads(path.read_text()), run_id) if path.is_file() else None

    pdf = next(out_dir.glob("*.pdf"))
    return {
        "migration.patch": (out_dir / "migration.patch").read_bytes(),
        "metrics.json": load("metrics.json"),
        "trajectory.json": load("trajectory.json"),
        "test_report.json": load("test_report.json"),
        "verification.json": load("verification.json"),
        "report.json": load("report.json"),
        "pdf_text": [_text(p.extract_text(), run_id) for p in PdfReader(pdf).pages],
        "pdf_name": _text(pdf.name, run_id),
    }


def _first_difference(a: Any, b: Any, path: str = "") -> str | None:
    if type(a) is not type(b):
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if (d := _first_difference(a.get(key), b.get(key), f"{path}.{key}")) is not None:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            if (d := _first_difference(x, y, f"{path}[{i}]")) is not None:
                return d
        return None
    return None if a == b else f"{path}: {str(a)[:200]!r} != {str(b)[:200]!r}"


@needs_docker
@pytest.mark.parametrize("task", sorted(p.name for p in TIER_A.iterdir() if p.is_dir()))
def test_tier_a_runs_are_reproducible(tmp_path: Path, task: str) -> None:
    snapshots = []
    for n in range(REPEATS):
        run_id = f"det{n}{task[:6]}"
        result = run_with_report(
            TIER_A / task, run_id=run_id, runs_dir=tmp_path / "runs", corrector=codemod_corrector
        )
        snapshots.append(_snapshot(result["out_dir"], run_id))
    assert snapshots[0]["migration.patch"] and snapshots[0]["report.json"], "control: real output"
    problems = [
        f"run {n} vs run 0, {artifact}: {diff}"
        for n in range(1, REPEATS)
        for artifact in snapshots[0]
        if (diff := _first_difference(snapshots[0][artifact], snapshots[n][artifact], artifact))
    ]
    assert not problems, "\n".join(problems)
