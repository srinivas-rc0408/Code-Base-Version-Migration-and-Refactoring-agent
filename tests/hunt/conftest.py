"""Bug-hunt harnesses (hypothesis, docker). Part of the default run.

Hypothesis profiles: "default" keeps the run fast; HYPOTHESIS_PROFILE=hunt
runs the full 500-example hunt.

Each test that reproduces a logged bug is marked ``xfail(strict=True)`` with
its BUGS.md id, so the hunt stays runnable while the bugs are open and turns
red the moment a fix lands (the marker must then be removed).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from hypothesis import settings

ROOT = Path(__file__).resolve().parents[2]
TIER_A = ROOT / "corpus" / "tierA"
BLIND = ROOT / "corpus" / "blind"

settings.register_profile("default", max_examples=20)
settings.register_profile("hunt", max_examples=500)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))


def docker_ok() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "image", "inspect", "mra-sandbox:py312"],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
    except OSError:
        return False


needs_docker = pytest.mark.skipif(not docker_ok(), reason="docker sandbox image not available")


def bug(bug_id: str, summary: str) -> pytest.MarkDecorator:
    """Mark a test that reproduces an open BUGS.md entry."""
    return pytest.mark.xfail(strict=True, reason=f"{bug_id}: {summary}")
