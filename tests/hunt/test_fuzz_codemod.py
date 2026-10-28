"""Hunt 1 — property-based fuzzing of MAP (finder) + EDIT (codemod).

Invariants, on every generated repo:

* finder count == generated true sites, and every reported site is on a
  ``# S`` line (zero decoys matched);
* codemod output parses; a second MAP+EDIT pass changes nothing;
* outside the target calls the AST is unchanged (imports aside), and every
  site reads exactly as the contract says;
* an import is added only when a class-form binding needs ``timezone``;
* the migrated repo runs with ``-W error::DeprecationWarning`` (semantic oracle).

A failing example is saved (spec + rendered files) under
``fixtures/<test name>/`` and replayed by :func:`test_saved_fixtures_replay`.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings

from mra.analysis.call_sites import find_in_repo
from mra.codemods.datetime_utcnow import TARGETS
from mra.nodes.edit_node import apply_codemod
from tests.hunt import repogen
from tests.hunt.conftest import bug

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = settings().max_examples  # from the profile loaded in conftest
FUZZ = settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    derandomize=True,  # the hunt is reproducible; a new seed is a deliberate change
    print_blob=True,
)


class _StripImports(ast.NodeTransformer):
    def visit_Import(self, node: ast.AST) -> None:
        return None

    def visit_ImportFrom(self, node: ast.AST) -> None:
        return None


def _shape(source: str) -> str:
    return ast.dump(_StripImports().visit(ast.parse(source)))


def _imports(source: str) -> Counter:
    """Every import statement as (module, name, alias) bindings, anywhere in the file."""
    found: Counter = Counter()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(("import", a.name, a.asname) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.update(
                (f"{'.' * node.level}{node.module or ''}", a.name, a.asname) for a in node.names
            )
    return found


def _run(root: Path, code: str, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *flags, "-c", code],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )


def _save(name: str, spec: dict, files: dict[str, str]) -> None:
    dest = FIXTURES / name
    shutil.rmtree(dest, ignore_errors=True)
    for relative, source in files.items():
        (dest / "repo" / relative).parent.mkdir(parents=True, exist_ok=True)
        (dest / "repo" / relative).write_text(source)
    (dest / "spec.json").write_text(json.dumps(spec, indent=1) + "\n")


def check_invariants(spec: dict) -> None:
    files = repogen.render(spec)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for relative, source in files.items():
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text(source)

        # The generator itself must be sound: the old tree runs.
        old_run = _run(root, repogen.driver(spec), "-W", "ignore")
        assert old_run.returncode == 0, f"generator bug: {old_run.stderr[-800:]}"

        # -- MAP: count, and only on true-site lines --------------------------
        found = find_in_repo(root, TARGETS)
        for i, module in enumerate(spec["modules"]):
            relative = f"pkg/m{i}.py"
            lines = files[relative].split("\n")
            want = sum(1 for item in module["items"] if item["kind"] == "site")
            got = found.get(relative, [])
            decoys = [s for s in got if not lines[s["line"] - 1].endswith("  # S")]
            assert not decoys, (
                f"{relative}: decoy matched: {[lines[s['line'] - 1] for s in decoys]}"
            )
            assert len(got) == want, f"{relative}: finder found {len(got)} of {want} true sites"
        assert set(found) <= {f"pkg/m{i}.py" for i in range(len(spec["modules"]))}

        # -- EDIT --------------------------------------------------------------
        apply_codemod(root, found)
        migrated = {r: (root / r).read_text() for r in files}
        for source in migrated.values():
            ast.parse(source)  # parses

        for i, module in enumerate(spec["modules"]):
            relative = f"pkg/m{i}.py"
            after = migrated[relative]
            # Outside the sites, nothing moved; at the sites, the contract's exact text.
            assert _shape(after) == _shape(repogen.expected_source(module)), (
                f"{relative}: collateral edit or wrong rewrite\n--- got ---\n{after}"
            )
            added = _imports(after) - _imports(files[relative])
            removed = _imports(files[relative]) - _imports(after)
            assert not removed, f"{relative}: imports removed {removed}"
            if repogen.needs_timezone_import(module):
                assert added == Counter({("datetime", "timezone", None): 1}), (
                    f"{relative}: expected exactly `timezone` imported, got {dict(added)}\n{after}"
                )
            else:
                assert not added, f"{relative}: unnecessary import(s) {dict(added)}\n{after}"
        for relative in ("pkg/__init__.py", "pkg/compat.py", "pkg/compat2.py"):
            assert migrated[relative] == files[relative], f"{relative} touched"

        # -- idempotent: a second full pass is a no-op ---------------------------
        again = find_in_repo(root, TARGETS)
        assert again == {}, f"residual sites after migration: {again}"
        apply_codemod(root, again)
        assert {r: (root / r).read_text() for r in files} == migrated

        # -- semantics: the migrated tree runs with the deprecation as an error --
        new_run = _run(root, repogen.driver(spec), "-W", "error::DeprecationWarning")
        assert new_run.returncode == 0, f"migrated tree fails: {new_run.stderr[-800:]}"


def _checked(name: str, spec: dict) -> None:
    try:
        check_invariants(spec)
    except AssertionError:
        # The last failing call hypothesis makes is the shrunk example.
        _save(name, spec, repogen.render(spec))
        raise


# -- the fuzz targets ----------------------------------------------------------


@FUZZ
@given(repogen.repo_specs())
def test_fuzz_core_styles(spec: dict) -> None:
    """All import styles that are expected to work, random contexts and decoys."""
    _checked("fuzz_core_styles", spec)


@bug("BUG-01", "class reached through an in-repo module gets `compat.timezone.utc`")
@settings(FUZZ, max_examples=max(1, EXAMPLES // 5))
@given(repogen.repo_specs(styles=(*repogen.CORE_STYLES, "reexport_attr")))
def test_fuzz_with_module_attribute_reexport(spec: dict) -> None:
    """``from pkg import compat; compat.datetime.utcnow()`` mixed in."""
    _checked("fuzz_with_module_attribute_reexport", spec)


@bug("BUG-02", "alias named `timezone` is clobbered by the inserted timezone import")
@settings(FUZZ, max_examples=max(1, EXAMPLES // 5))
@given(repogen.repo_specs(styles=("from_alias",), extra_aliases=("timezone",)))
def test_fuzz_alias_named_timezone(spec: dict) -> None:
    """``from datetime import datetime as timezone`` is legal Python."""
    _checked("fuzz_alias_named_timezone", spec)


def _fixture_specs() -> list[Path]:
    return sorted(FIXTURES.glob("*/spec.json")) if FIXTURES.is_dir() else []


@pytest.mark.parametrize("spec_path", _fixture_specs(), ids=lambda p: p.parent.name)
def test_saved_fixtures_replay(spec_path: Path) -> None:
    """Every saved shrunk example still reproduces (each is a logged bug)."""
    with pytest.raises(AssertionError):
        check_invariants(json.loads(spec_path.read_text()))
