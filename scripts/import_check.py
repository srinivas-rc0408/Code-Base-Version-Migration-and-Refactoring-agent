"""Import accuracy (docs/05 §2.3a) for archived runs, recomputed from their patches.

Each ``EVIDENCE_DIR/<run_id>/migration.patch`` is applied in memory to its task's
``corpus/.../old`` tree and scored with :func:`mra.metrics.imports` against
``expected_import_changes``. ``-rerun`` runs started from the agent's own output,
not from old/, so they are listed as n/a. Prints a Markdown table.

Usage: python scripts/import_check.py EVIDENCE_DIR
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from mra.metrics import imports, source_tree

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def apply_patch(files: dict[str, bytes], patch: str) -> dict[str, bytes]:
    """``git diff`` text applied to ``{path: bytes}``; a strict, in-memory ``git apply``."""
    out = dict(files)
    blocks = re.split(r"^diff --git .*\n", patch, flags=re.M)[1:]
    for block in blocks:
        lines = block.splitlines(keepends=True)
        old_path = next(x[6:].strip() for x in lines if x.startswith(("--- a/", "--- /dev")))
        new_path = next(x[6:].strip() for x in lines if x.startswith(("+++ b/", "+++ /dev")))
        src = out.get(old_path, b"").decode().splitlines(keepends=True)
        result: list[str] = []
        cursor = 0
        for i, line in enumerate(lines):
            if not (m := HUNK.match(line)):
                continue
            start = int(m.group(1)) - (0 if m.group(2) == "0" else 1)
            result += src[cursor:start]
            cursor = start
            for body in lines[i + 1 :]:
                if body.startswith(("@@", "diff --git")):
                    break
                if body.startswith("\\"):  # "\ No newline at end of file"
                    if result:
                        result[-1] = result[-1].rstrip("\n")
                    continue
                tag, text = body[:1], body[1:]
                if tag in (" ", "-"):
                    assert src[cursor].rstrip("\n") == text.rstrip("\n"), (old_path, cursor)
                    cursor += 1
                if tag in (" ", "+"):
                    result.append(text)
        result += src[cursor:]
        if new_path != "dev/null":
            out[new_path] = "".join(result).encode()
        if old_path != new_path:
            out.pop(old_path, None)
    return out


def task_dir(run_id: str, evidence: Path) -> Path | None:
    if run_id.startswith("blind07-"):
        return None if run_id.endswith("-rerun") else CORPUS / "blind" / "task07_cache"
    task = json.loads((evidence / run_id / "metrics.json").read_text())["task_id"]
    return CORPUS / "tierA" / task


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("evidence_dir", type=Path)
    evidence = parser.parse_args().evidence_dir
    print("| run | task | imports | expected | spurious | missing |")
    print("|---|---|---|---|---|---|")
    for run in sorted(p for p in evidence.iterdir() if p.is_dir()):
        task = task_dir(run.name, evidence)
        if task is None:
            print(f"| {run.name} | task07_cache | n/a (re-run on own output) |  |  |  |")
            continue
        old = source_tree(task / "old")
        new = apply_patch(old, (run / "migration.patch").read_text())
        truth = json.loads((task / "ground_truth.json").read_text())
        s = imports(old, new, truth.get("expected_import_changes"))
        print(
            f"| {run.name} | {task.name} | {s['accuracy']:.1f}% | {s['expected']} | "
            f"{', '.join(s['spurious']) or '—'} | {', '.join(s['missing']) or '—'} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
