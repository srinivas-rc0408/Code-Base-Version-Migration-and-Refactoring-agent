"""Hunt 7 — the report under stress: a 10k-line diff, 300-character file names,
non-ASCII paths, 500 files. The PDF must stay within 14 pages, parse, and still
say what it is about (verdict on the first and last page, paths legible).
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from pypdf import PdfReader

from mra.report.model import build_model
from mra.report.pdf import MAX_PAGES, render
from tests.hunt.conftest import bug
from tests.test_report import _synthetic_run


def _rename(run: dict[str, Any], rename: Any) -> dict[str, Any]:
    """Apply ``rename`` to every file path in a synthetic run (model inputs only)."""
    old = list(run["state"]["call_sites"])
    new = {f: rename(i, f) for i, f in enumerate(old)}
    run["state"]["call_sites"] = {
        new[f]: [{**s, "file": new[f]} for s in sites]
        for f, sites in run["state"]["call_sites"].items()
    }
    run["state"]["dep_graph"] = {
        new[f]: [new[t] for t in ts] for f, ts in run["state"]["dep_graph"].items()
    }
    run["state"]["file_status"] = {new[f]: v for f, v in run["state"]["file_status"].items()}
    for f in old:
        run["patch"] = run["patch"].replace(f, new[f])
    for event in run["trajectory"]:
        for key in ("batches", "files", "changed"):
            if key in event["detail"]:
                value = event["detail"][key]
                event["detail"][key] = (
                    [[new.get(f, f) for f in b] for b in value]
                    if value and isinstance(value[0], list)
                    else [new.get(f, f) for f in value]
                )
    ev = run["evidence"]
    ev["inventory"] = [{**e, "file": new[e["file"]]} for e in ev["inventory"]]
    ev["semantic"] = [{**e, "file": new[e["file"]]} for e in ev["semantic"]]
    ev["coverage"]["files"] = {new[f]: v for f, v in ev["coverage"]["files"].items()}
    run["semantic"], run["coverage"] = ev["semantic"], ev["coverage"]
    return run


def _render(run: dict[str, Any]) -> tuple[list[str], dict[str, Any], int]:
    model = build_model(run)
    data, pages, cuts = render(model, generated="2026-10-06 00:00 UTC")
    text = [p.extract_text() for p in PdfReader(io.BytesIO(data)).pages]
    assert pages == len(text)
    return text, cuts, len(data)


def _check(text: list[str]) -> None:
    assert len(text) <= MAX_PAGES, f"{len(text)} pages > {MAX_PAGES}"
    assert "GREEN" in text[0] and "GREEN" in text[-1]


UNCAPPED = bug("BUG-17", "the per-file Changes table is never truncated: >~400 files raises")


@UNCAPPED
def test_500_files() -> None:
    _check(_render(_synthetic_run(500))[0])


def test_300_character_file_names_100_files() -> None:
    """The long-name half of the stress, below the file count that trips BUG-17."""

    def long(i: int, f: str) -> str:
        return (f"src/d{i:03d}/" + "/".join(["y" * 99] * 3))[: 300 - 3] + ".py"

    _check(_render(_rename(_synthetic_run(100), long))[0])


def test_10k_line_diff() -> None:
    run = _synthetic_run(3)
    f = "src/pkg/mod000.py"
    body = "".join(f"+    line_{i} = {i}\n" for i in range(10_000))
    run["patch"] += f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1,1 +1,10001 @@\n x\n{body}"
    _check(_render(run)[0])


@UNCAPPED
def test_300_character_file_names_500_files() -> None:
    def long(i: int, f: str) -> str:
        head = f"src/d{i:03d}/"
        tail = "/".join(["x" * 99] * 3)
        return (head + tail)[: 300 - 3] + ".py"

    run = _rename(_synthetic_run(500), long)
    assert all(len(f) == 300 for f in run["state"]["call_sites"])
    _check(_render(run)[0])


@pytest.mark.parametrize(
    "name",
    [
        "src/paquete/módulo_ñandú.py",
        pytest.param(
            "src/пакет/модуль.py",
            marks=bug("BUG-16", "Cyrillic/CJK paths are dropped from the PDF"),
        ),
        pytest.param(
            "src/包/模块_时间.py",
            marks=bug("BUG-16", "Cyrillic/CJK paths are dropped from the PDF"),
        ),
    ],
)
def test_non_ascii_paths_are_legible(name: str) -> None:
    run = _rename(_synthetic_run(3), lambda i, f: name.replace(".py", f"_{i}.py"))
    text = _render(run)[0]
    _check(text)
    stem = name.rsplit("/", 1)[-1].replace(".py", "")
    assert stem in "".join(text).replace("\n", ""), f"{stem!r} not legible in the PDF"
