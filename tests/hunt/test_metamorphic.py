"""Hunt 2 — metamorphic tests: the same input in another form, the same answer.

For a transform ``T`` of a repo, MAP must report the same sites (per
transformed file) and EDIT must commute with ``T``:
``migrate(T(repo)) == T(migrate(repo))``. Transforms: identifier renaming
(modules, packages, aliases), file reordering (names that sort the other way),
CRLF, tabs, and the repo's *location* — a path with spaces and non-ASCII
characters (the real checkout has spaces), a symlinked path, and a path with an
ordinary directory name like ``build`` in it.

The location transforms are also run through the full agent (docker), which
must give the same verdict and the same migration.patch.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import libcst as cst
import pytest
from hypothesis import given, settings

from mra.analysis.call_sites import find_in_repo
from mra.codemods.datetime_utcnow import TARGETS
from mra.nodes.edit_node import apply_codemod
from tests.hunt import repogen
from tests.hunt.conftest import TIER_A, needs_docker
from tests.hunt.test_fuzz_codemod import FUZZ

Files = dict[str, bytes]
EXAMPLES = max(1, settings().max_examples // 4)


def _write(root: Path, files: Files) -> None:
    for relative, data in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(data)


def _read(root: Path) -> Files:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts
    }


def migrate(root: Path, files: Files) -> tuple[dict[str, int], Files]:
    """(sites per file, files after EDIT) for ``files`` written under ``root``."""
    _write(root, files)
    found = find_in_repo(root, TARGETS)
    apply_codemod(root, found)
    return {f: len(s) for f, s in found.items()}, _read(root)


# -- transforms ------------------------------------------------------------------


class _Rename(cst.CSTTransformer):
    def __init__(self, names: dict[str, str]) -> None:
        self.names = names

    def leave_Name(self, original: cst.Name, updated: cst.Name) -> cst.Name:
        return updated.with_changes(value=self.names.get(updated.value, updated.value))


def renamer(names: dict[str, str], paths: dict[str, str]) -> Callable[[Files], Files]:
    def transform(files: Files) -> Files:
        out = {}
        for relative, data in files.items():
            if relative.endswith(".py"):
                data = cst.parse_module(data).visit(_Rename(names)).bytes
            for old, new in paths.items():
                relative = relative.replace(old, new)
            out[relative] = data
        return out

    return transform


def crlf(files: Files) -> Files:
    return {r: d.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") for r, d in files.items()}


def tabs(files: Files) -> Files:
    def line(text: bytes) -> bytes:
        stripped = text.lstrip(b" ")
        depth = (len(text) - len(stripped)) // 4
        return b"\t" * depth + b" " * ((len(text) - len(stripped)) % 4) + stripped

    return {r: b"\n".join(line(x) for x in d.split(b"\n")) for r, d in files.items()}


def _aliases(spec: dict) -> dict[str, str]:
    # The renamer rewrites every Name, so an alias spelled like an identifier the
    # migration emits (timezone.utc, .now) would corrupt the expected output.
    emitted = {"datetime", "compat", "timezone", "utc", "now"}
    names = {b["name"] for m in spec["modules"] for b in m["bindings"]} - emitted
    return {name: f"renamed_{i}" for i, name in enumerate(sorted(names))}


def _commutes(tmp: Path, files: Files, transform: Callable[[Files], Files]) -> None:
    sites, migrated = migrate(tmp / "a", files)
    t_sites, t_migrated = migrate(tmp / "b", transform(files))
    assert sorted(t_sites.values()) == sorted(sites.values()), "verdict (site counts) differs"
    assert sum(t_sites.values()) == sum(sites.values())
    expected = transform(migrated)
    diffs = [r for r in expected if expected[r] != t_migrated.get(r)]
    assert not diffs, f"patch differs under transform in {diffs}:\n" + (
        t_migrated.get(diffs[0], b"<missing>").decode(errors="replace")
    )


def _files(spec: dict) -> Files:
    return {r: s.encode() for r, s in repogen.render(spec).items()}


MOVE = {"pkg/": "pkg_moved/", "compat": "kompat"}


@settings(FUZZ, max_examples=EXAMPLES)
@given(repogen.repo_specs())
def test_rename_modules_and_aliases(tmp_path_factory: pytest.TempPathFactory, spec: dict) -> None:
    names = {**_aliases(spec), "pkg": "pkg_moved", "compat": "kompat", "compat2": "kompat2"}
    _commutes(tmp_path_factory.mktemp("r"), _files(spec), renamer(names, MOVE))


@settings(FUZZ, max_examples=EXAMPLES)
@given(repogen.repo_specs())
def test_reorder_files(tmp_path_factory: pytest.TempPathFactory, spec: dict) -> None:
    """Module names that sort in the opposite order (m0 -> z9_m0, m1 -> z8_m1 ...)."""
    paths = {f"pkg/m{i}.py": f"pkg/z{9 - i}_m{i}.py" for i in range(len(spec["modules"]))}
    _commutes(tmp_path_factory.mktemp("o"), _files(spec), renamer({}, paths))


@settings(FUZZ, max_examples=EXAMPLES)
@given(repogen.repo_specs())
def test_crlf_vs_lf(tmp_path_factory: pytest.TempPathFactory, spec: dict) -> None:
    _commutes(tmp_path_factory.mktemp("c"), _files(spec), crlf)


@settings(FUZZ, max_examples=EXAMPLES)
@given(repogen.repo_specs())
def test_tabs_vs_spaces(tmp_path_factory: pytest.TempPathFactory, spec: dict) -> None:
    _commutes(tmp_path_factory.mktemp("t"), _files(spec), tabs)


# -- the repo's location ---------------------------------------------------------

LOCATIONS = {
    "spaces_non_ascii": "Major Project 1- CodeBase-version/ünïcødé dír/repo",
    "colon_in_path": "odd:name/repo",
    "build_component": "build/repo",
    "dist_component": "work/dist/repo",
    "venv_component": "venv/projects/repo",
}


def _tier_a(task: str) -> Files:
    return _read(TIER_A / task / "old")


@pytest.mark.parametrize("location", sorted(LOCATIONS))
@pytest.mark.parametrize("task", sorted(p.name for p in TIER_A.iterdir() if p.is_dir()))
def test_location_does_not_change_the_answer(tmp_path: Path, task: str, location: str) -> None:
    files = _tier_a(task)
    sites, migrated = migrate(tmp_path / "plain" / "repo", files)
    assert sites, "control: every Tier-A task has sites"
    moved_sites, moved = migrate(tmp_path / LOCATIONS[location], files)
    assert moved_sites == sites
    assert moved == migrated


@pytest.mark.parametrize("task", sorted(p.name for p in TIER_A.iterdir() if p.is_dir()))
def test_symlinked_repo_path(tmp_path: Path, task: str) -> None:
    files = _tier_a(task)
    sites, migrated = migrate(tmp_path / "real" / "repo", files)
    (tmp_path / "other").mkdir()
    _write(tmp_path / "other" / "repo", files)
    (tmp_path / "link").symlink_to(tmp_path / "other" / "repo")
    linked_sites, _ = migrate(tmp_path / "link", {})
    assert linked_sites == sites
    assert _read(tmp_path / "other" / "repo") == migrated


# -- full agent: verdict + patch under location transforms -------------------------


def _full_run(task_dir: Path, runs_dir: Path, run_id: str) -> tuple[str, str, list[str]]:
    from mra.benchmark.runner import codemod_corrector
    from mra.report import run_with_report

    result = run_with_report(
        task_dir, run_id=run_id, runs_dir=runs_dir, corrector=codemod_corrector
    )
    model = result["model"]
    patch = (result["out_dir"] / "migration.patch").read_text()
    return model["verdict"]["status"], patch, sorted(r["code"] for r in model["issues"])


@needs_docker
@pytest.mark.parametrize(
    "where",
    [
        "Major Project 1- CodeBase-version/ünïcødé dír",
        "symlink",
        "build",
    ],
)
def test_full_run_location_invariance(tmp_path: Path, where: str) -> None:
    task = "task04_multimodule"
    base = _full_run(TIER_A / task, tmp_path / "plain_runs", "base")
    if where == "symlink":
        shutil.copytree(TIER_A / task, tmp_path / "real" / task)
        (tmp_path / "link").symlink_to(tmp_path / "real")
        task_dir, runs = tmp_path / "link" / task, tmp_path / "link" / "runs"
    else:
        shutil.copytree(TIER_A / task, tmp_path / where / task)
        task_dir, runs = tmp_path / where / task, tmp_path / where / "runs"
    moved = _full_run(task_dir, runs, "moved")
    assert moved[0] == base[0] == "GREEN", f"verdicts: base {base[0]}, moved {moved[0]} {moved[2]}"
    assert moved[1] == base[1], "migration.patch differs"
    json.dumps(moved)  # the outcome is plain data
