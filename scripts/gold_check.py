"""Compare each live run's final migrated tree against its task's gold/ tree.

For the runs cited in ``benchmark/live/results_live.json`` plus every ``blind07-*`` run:
source files are compared to gold with docstrings ignored (gold rewrites prose the
agent never touches), a file shorter than gold or a gold function/class missing from
the run is flagged, tests and config must be byte-identical to old/, and every
old -> run diff hunk must sit on a ground-truth call site, a line gold also changed,
or an import. Read-only; prints a Markdown table and exits 1 if any run is suspicious.

Usage: python scripts/gold_check.py RUNS_DIR [--self-test]
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
SKIP = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".coverage", ".mypy_cache"}
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def tree(root: Path) -> dict[str, bytes]:
    out = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.endswith(".egg-info")]
        for name in files:
            if name not in SKIP and not name.endswith(".pyc"):
                path = Path(dirpath) / name
                out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


def strip_docs(src: bytes) -> str:
    module = ast.parse(src)
    for node in ast.walk(module):
        body = getattr(node, "body", None)
        if (
            isinstance(node, (ast.Module, *DEFS))
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body[0] = ast.Pass()
    return ast.dump(module)


def defs(src: bytes) -> set[str]:
    names: set[str] = set()

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, DEFS):
                names.add(prefix + child.name)
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(ast.parse(src), "")
    return names


def stmts(src: bytes) -> int:
    return sum(isinstance(n, ast.stmt) for n in ast.walk(ast.parse(src)))


def hunks(a: bytes, b: bytes) -> list[tuple[int, int, list[str], list[str]]]:
    """``a -> b`` as (old_start, old_end_exclusive, removed, added), 1-based."""
    al, bl = a.decode().splitlines(), b.decode().splitlines()
    matcher = difflib.SequenceMatcher(None, al, bl, autojunk=False)
    return [
        (i1 + 1, i2 + 1, al[i1:i2], bl[j1:j2])
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def is_import(line: str) -> bool:
    s = line.strip()
    return s == "" or s.startswith(("import ", "from "))


def check(run_dir: Path, task_dir: Path) -> dict[str, Any]:
    """One run's final ``repo/`` against ``task_dir``'s old/, gold/ and ground truth."""
    old, gold, run = tree(task_dir / "old"), tree(task_dir / "gold"), tree(run_dir / "repo")
    sites: dict[str, set[int]] = {}
    for site in json.loads((task_dir / "ground_truth.json").read_text()).get("call_sites", []):
        sites.setdefault(site["file"], set()).add(site["line"])

    source = sorted(f for f in {*gold, *run} if f.endswith(".py") and not f.startswith("tests/"))
    differ: list[str] = []
    shorter: list[str] = []
    missing: list[str] = []
    unexpected: list[str] = []
    for f in source:
        if f not in run:
            missing.append(f"{f} (whole file)")
            continue
        if f not in gold:
            unexpected.append(f"{f}: not in gold")
            continue
        g, r = gold[f], run[f]
        if strip_docs(g) != strip_docs(r):
            differ.append(f)
        lines_r, lines_g = r.count(b"\n"), g.count(b"\n")
        if lines_r < lines_g or stmts(r) < stmts(g):
            shorter.append(f"{f} ({lines_r}/{lines_g} lines, {stmts(r)}/{stmts(g)} stmts)")
        missing += [f"{f}:{name}" for name in sorted(defs(g) - defs(r))]
        if f not in old:
            continue
        allowed = set(sites.get(f, set()))
        for i1, i2, _, _ in hunks(old[f], g):
            allowed |= set(range(i1, max(i2, i1 + 1)))
        gold_lines = {line.strip() for line in g.decode().splitlines()}
        for i1, i2, removed, added in hunks(old[f], r):
            removed_ok = all(i1 + k in allowed or is_import(x) for k, x in enumerate(removed))
            added_ok = all(
                is_import(x) or x.strip() in gold_lines or "timezone.utc" in x for x in added
            )
            if not (removed_ok and added_ok):
                unexpected.append(f"{f}:{i1}-{i2 - 1} -{removed!r} +{added!r}")

    for f in sorted(f for f in {*old, *run} if f not in source):  # tests, config: exactly old
        if old.get(f) != run.get(f):
            unexpected.append(f"{f}: differs from old/ (tests/config must be untouched)")

    return {
        "differ": differ,
        "shorter": shorter,
        "missing": missing,
        "unexpected": unexpected,
        "suspicious": bool(shorter or missing or unexpected),
    }


def jobs(runs: Path) -> list[tuple[str, str, Path, Path]]:
    rows = json.loads((runs / "benchmark/live/results_live.json").read_text())["rows"]
    out = [
        (r["run_id"], r["task_id"], runs / "benchmark/live/runs" / r["run_id"], CORPUS / "tierA")
        for r in rows
    ]
    for d in sorted(runs.glob("blind07-*")):
        if (d / "repo").is_dir():
            out.append((d.name, "task07_cache", d, CORPUS / "blind"))
    return [(rid, task, d, tier / task) for rid, task, d, tier in out]


def self_test(runs: Path) -> list[str]:
    """Plant four faults in copies of a task04 run; each must be flagged."""
    rid, _, run_dir, task_dir = next(j for j in jobs(runs) if j[1] == "task04_multimodule")

    def drop_last_def(repo: Path) -> None:
        p = repo / "src/pkg/ledger.py"
        s = p.read_text()
        p.write_text(s[: s.rindex("\ndef ")].rstrip() + "\n")

    def cut_tail(repo: Path) -> None:
        p = repo / "src/pkg/invoice.py"
        p.write_text("".join(p.read_text().splitlines(True)[:-2]))

    def stray_line(repo: Path) -> None:
        p = repo / "src/pkg/api.py"
        p.write_text(p.read_text().replace("\n\n", "\n\nUNRELATED = 42\n", 1))

    def edit_test(repo: Path) -> None:
        p = sorted((repo / "tests").glob("test_*.py"))[0]
        p.write_text(p.read_text() + "\n# weakened\n")

    out = []
    for fault in (drop_last_def, cut_tail, stray_line, edit_test):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(run_dir / "repo", Path(tmp) / "repo")
            fault(Path(tmp) / "repo")
            flagged = check(Path(tmp), task_dir)["suspicious"]
        out.append(f"{fault.__name__} on {rid}: {'flagged' if flagged else 'MISSED'}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "runs_dir", type=Path, help="directory holding benchmark/live and blind07-*"
    )
    parser.add_argument("--self-test", action="store_true", help="also run the planted faults")
    args = parser.parse_args()

    print("| run | task | files differing from gold | missing definitions | verdict |")
    print("|---|---|---|---|---|")
    bad = 0
    for rid, task, run_dir, task_dir in jobs(args.runs_dir):
        r = check(run_dir, task_dir)
        bad += r["suspicious"]
        differ = f"{len(r['differ'])}" + (f" ({', '.join(r['differ'])})" if r["differ"] else "")
        verdict = "suspicious" if r["suspicious"] else "clean"
        print(f"| {rid} | {task} | {differ} | {len(r['missing'])} | {verdict} |")
        for detail in r["shorter"] + r["missing"] + r["unexpected"]:
            print(f"|  |  | {detail} |  |  |")
    if args.self_test:
        print()
        print("\n".join(f"- {line}" for line in self_test(args.runs_dir)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
