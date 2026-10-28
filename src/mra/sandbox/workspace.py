"""The run's writable copy of the input repo, which never reaches outside it."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class UnsafeRepoError(RuntimeError):
    """The input repo holds a symlink that leaves it; the run is refused, nothing is read."""


def copy_repo(source: Path, dest: Path) -> None:
    """Copy ``source`` to ``dest`` with links kept as links and the user's ``.git`` left out.

    A link is never followed. If any link in the copy resolves outside ``dest``
    (a target elsewhere on disk, or an absolute path back into ``source``), the
    copy is deleted and :class:`UnsafeRepoError` names every offending link.
    """
    # Without .git: the run's first commit must be its own pre-migration snapshot.
    shutil.copytree(source, dest, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    root = dest.resolve()
    escaping = []
    for dirpath, dirnames, filenames in os.walk(dest):
        for name in dirnames + filenames:
            link = Path(dirpath) / name
            if link.is_symlink() and not link.resolve().is_relative_to(root):
                escaping.append(f"{link.relative_to(dest)} -> {os.readlink(link)}")
    if escaping:
        shutil.rmtree(dest)  # rmtree removes links, never their targets
        raise UnsafeRepoError(
            f"{len(escaping)} symlink(s) point outside the repo and were not followed: "
            + ", ".join(sorted(escaping))
        )
