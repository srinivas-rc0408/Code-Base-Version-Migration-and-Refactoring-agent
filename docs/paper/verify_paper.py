"""Check paper.md against the artefacts it cites. Run after any benchmark rerun.

The paper's provenance rule (see its header comment) is that a `<!-- SOURCE: -->`
comment covers every line above it back to the previous SOURCE or the nearest
heading. This script enforces that rule mechanically for the Abstract and
§3-§4, §7-§9, re-diffs the §7.1 and §7.8 tables against their results.md, and
re-derives the §8 counts from failure-analysis.md and results.json. It exists
because the §7.1 grid has silently gone stale once.

The post-P5 sections (§3.6, §4.4, §7.7, §7.8, §8.1, §9 item 6) are checked
phrase by phrase against corpus/edge/results.json, the ablation-E results and
the bb1dd07 commit message. The §8.1 defect count is the number of rows in its
fix table, and every regression test that table names must exist in tests/.

RESULTS_SUMMARY.md gets the same treatment for a different reason: the paper's
SOURCE pointers cite it, but unlike results.md nothing regenerates it, so a
benchmark rerun moves the run records and leaves the summary behind in silence.
Every cell of its four tables is re-derived here from results.json, and any
figure in a cell the grammar does not recognise is reported rather than skipped.

    python docs/paper/verify_paper.py      # exit 0 = every check passes
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "docs/paper/paper.md"
RESULTS_MD = ROOT / "runs/benchmark/results.md"
RESULTS_JSON = ROOT / "runs/benchmark/results.json"
FAILURES_MD = ROOT / "runs/benchmark/failure-analysis.md"
SUMMARY_MD = ROOT / "runs/benchmark/RESULTS_SUMMARY.md"
EDGE_JSON = ROOT / "corpus/edge/results.json"
ABLATION_E_MD = ROOT / "runs/benchmark/ablation-e/results.md"
ABLATION_E_JSON = ROOT / "runs/benchmark/ablation-e/results.json"
EXPERIENCE_PY = ROOT / "src/mra/memory/experience.py"
BLIND = ROOT / "corpus/blind/task06_scheduler"
BLIND07 = ROOT / "corpus/blind/task07_cache"
GOLD_CHECK_MD = ROOT / "runs/benchmark/live/evidence/GOLD_CHECK.md"
BUGS_MD = ROOT / "BUGS.md"
HUNT = ROOT / "tests/hunt"
# Each blind claim is checked over history: src/ unchanged from the freeze to the
# commit that recorded the blind result, which later commits cannot alter.
FROZEN_AT, BLIND_COMMIT = "f97bf67", "10ebb17"
FROZEN07_AT, BLIND07_COMMIT = "06da274", "bcf2c90"
# results.json as published (P5); the v0.4.0 fixes must leave it untouched.
RESULTS_COMMIT = "c4815e8"
# The commit that found the vacuous leftover-container check and fixed BUG-19.
SILENT_CHECK_COMMIT = "7fac1e6"
TESTS = ROOT / "tests"
# The fix commit; its message is the only record of the post-fix matrix re-run.
FIX_COMMIT = "bb1dd07"

GRID_HEADER = (
    "| task / config | outcome | M1 recall | M1 prec | M1 F1 | M2 % "
    "| regr | corr | steps | tokens | cost $ | wall s |"
)
# `task05` is an identifier, not a figure; don't treat its digits as a claim.
# A leading "2. " is a list marker, not a figure.
IDENTIFIER_DIGITS = re.compile(
    r"^\s*\d+\.\s|task0\d|V4-|c-i{1,3}\b|§\d|FR-\d|NB-\d|NFR-\d|M[123]\b"
)
# Padding words cut from §1 by hand; a later pass must not reintroduce them.
INTENSIFIERS = r"\b(?:completely|absolutely|merely|significantly)\b"
# The Abstract spells its figures as words ("three of the five"), so a digit-only
# test would pass it with no pointer at all.
NUMBER_WORDS = re.compile(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\b", re.I)

LOOP_HEADER = "| task | loop on | loop off |"
ORDER_HEADER = "| task | dependency | file-name | dependents-first |"
E_HEADER = "| task | config | outcome | corrections | tokens | hints served | hint chars |"
FIX_HEADER = "| class | defect fixed | regression test |"
BLIND_HEADER = "| # | pass criterion | result | evidence (r1 / r2 / r3) |"
BASELINE_HEADER = (
    "| task | \\|A\\| | ruff detected | ruff fixed | M1 after fix "
    "| suite after fix | pyupgrade detected |"
)
# The ORDER_HEADER tables in document order: ablation B with the loop off, then
# the same three orders with it on. Ablation B's "dependency" arm is a distinct
# config only when recovery is off; with it on, dependency order at batch 1 is
# the `batch-1` config.
ORDER_CONFIGS = (
    (
        "order-dependency-b1-norecovery",
        "order-alphabetical-b1-norecovery",
        "order-fr3-violating-b1-norecovery",
    ),
    ("batch-1", "order-alphabetical-b1", "order-fr3-violating-b1"),
)
# How a summary cell spells each metric: "3x gave_up, M1 33, M2 85.7, 1 regr".
CELL_FIGURES = (
    ("repeats", re.compile(r"(\d+)×")),
    ("m1", re.compile(r"M1 (\d+(?:\.\d+)?)")),
    ("m2", re.compile(r"M2 (\d+(?:\.\d+)?)")),
    ("regr", re.compile(r"(\d+) regr")),
    ("corr", re.compile(r"(\d+) corr")),
)

results: list[tuple[bool, str]] = []


def check(condition: bool, message: str) -> None:
    results.append((bool(condition), message))


def table_after(lines: list[str], header: str) -> list[str]:
    i = lines.index(header)
    out = []
    while i < len(lines) and lines[i].startswith("|"):
        out.append(lines[i])
        i += 1
    return out


def carries_a_figure(line: str) -> bool:
    """True if the line states a number, ignoring identifiers that contain digits."""
    return bool(re.search(r"\d", IDENTIFIER_DIGITS.sub("", line)))


def states_a_count(line: str) -> bool:
    return carries_a_figure(line) or bool(NUMBER_WORDS.search(line))


def uncovered_spans(
    lines: list[str], s: int, e: int, is_claim=carries_a_figure
) -> tuple[int, list[str]]:
    """Claim lines in lines[s+1:e] whose span reaches a heading or `e` without a SOURCE comment."""
    pending: int | None = None
    pointers = 0
    gaps: list[str] = []
    in_comment = False
    for k in range(s + 1, e):
        line = lines[k]
        if in_comment:
            in_comment = "-->" not in line
            continue
        if line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
            pointers += 1
            pending = None
            continue
        if line.startswith("#"):
            if pending is not None:
                gaps.append(f"line {pending + 1}: {lines[pending][:60]!r}")
            pending = None
            continue
        if not line.startswith(">") and is_claim(line) and pending is None:
            pending = k
    if pending is not None:
        gaps.append(f"line {pending + 1}: {lines[pending][:60]!r}")
    return pointers, gaps


def section(lines: list[str], start: str, end: str) -> tuple[int, int]:
    s = next(i for i, line in enumerate(lines) if line.startswith(start))
    e = next(i for i, line in enumerate(lines) if line.startswith(end))
    return s, e


def tables_after(lines: list[str], header: str) -> list[list[str]]:
    """Every table under `header`, in document order, header and rule dropped."""
    return [table_after(lines[i:], header)[2:] for i, line in enumerate(lines) if line == header]


def cells(row: str) -> list[str]:
    return [c.strip().strip("*").strip() for c in row.strip().strip("|").split("|")]


def figures(text: str) -> list[float]:
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]


def commit_message(sha: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "show", "-s", "--format=%B", sha],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def pinned_defects(lines: list[str]) -> tuple[int, list[str]]:
    """Rows of the §8.1 fix table, and every regression test it names that tests/ lacks."""
    rows = table_after(lines, FIX_HEADER)[2:]
    missing = []
    for row in rows:
        for path, name in re.findall(r"`(test_\w+\.py)::(test_\w+)`", cells(row)[2]):
            if not re.search(rf"^def {name}\(", (TESTS / path).read_text(), re.M):
                missing.append(f"{path}::{name}")
        if not re.search(r"`test_\w+\.py::test_\w+`", row):
            missing.append(f"(no test named) {cells(row)[1]}")
    return len(rows), missing


def post_p5_claims(matrix: dict[str, Any], defects: int) -> dict[str, list[str]]:
    """The exact phrases the post-P5 sections must contain, built from their sources."""
    edge = json.loads(EDGE_JSON.read_text())
    cases = {c["case"]: c for c in edge["cases"]}
    by = lambda key, value: sum(1 for c in edge["cases"] if c[key] == value)  # noqa: E731
    hint_budget = re.search(r"HINT_BUDGET_CHARS = (\d+)", EXPERIENCE_PY.read_text()).group(1)

    abl = json.loads(ABLATION_E_JSON.read_text())
    agg = {(a["config"], a["task_id"][:6]): a for a in abl["aggregates"]}
    corr = lambda config, task: round(agg[(config, task)]["corrections_mean"])  # noqa: E731
    gave_up = [
        f"`{a['task_id'][:6]}`"
        for a in abl["aggregates"]
        if a["config"] == "memory-off" and list(a["outcomes"]) == ["gave_up"]
    ]
    warm = abl["experience_warmup"]
    (fix_class,) = warm["by_class"]

    rerun = re.search(r"identical\s+\((\d+)/(\d+)\)", commit_message(FIX_COMMIT))

    suites = [
        int(t["suite_after_fix"].split("/")[1].split()[0])
        for b in matrix["baselines"]
        for t in b["tools"]
        if t["tool"] == "ruff (DTZ)"
    ]
    gaps = ("bare_reference", "star_import", "deprecated_call_in_test_file")
    return {
        "§3.6 experience store": [f"capped at {hint_budget} characters"],
        "§4.4 edge suite": [
            f"holds **{edge['total']}** small repositories",
            f"**common ({by('category', 'common')})**",
            f"**rare ({by('category', 'rare')})**",
            f"**twisted ({by('category', 'twisted')})**",
            f"**failure ({by('category', 'failure')})**",
            f"{by('expected', 'GREEN')} GREEN, {by('expected', 'YELLOW')} YELLOW "
            f"and {by('expected', 'RED')} RED",
        ],
        "§7.7 edge accuracy": [
            f"version {edge['agent_version']}",
            f"**{edge['passed']} of {edge['total']}** edge cases",
            f"(generated {edge['generated_at'][:19]}Z)",
            f"surfaced {defects} defects in the verdict path, each now pinned",
        ],
        "§7.8 ablation E": [
            f"over {len(warm['train_tasks'])} edge-corpus tasks",
            f"stored {warm['fixes']} fix, of class `{fix_class}`",
            f"(generated {abl['generated_at'][:19]}Z, {abl['repeats']} repeats",
            f"need a corrective edit: {', '.join(gave_up[:-1])} and {gave_up[-1]}",
            f"`task03` with {corr('memory-warm', 'task03')} corrective edit",
            f"`task04` with {corr('memory-warm', 'task04')}, each run",
            f"gives up after {corr('memory-warm', 'task02')} corrective edits",
            f"its {len(abl['skipped'])} (task, config) pairs",
        ],
        "§8.1 edge-suite defects": [
            f"building it surfaced {defects} defects in the verdict path itself",
            f"the {rerun.group(2)}-row matrix was re-run",
            f"{rerun.group(1)} of {rerun.group(2)} rows",
        ],
        "§9 limitations": [
            *(
                f"`{case}`"
                if cases[case]["expected"] == cases[case]["actual"] == "YELLOW"
                else f"<{case} is no longer a YELLOW gap: {cases[case]['actual']}>"
                for case in gaps
            ),
            f"suites of {min(suites)}–{max(suites)} tests",
        ],
    }


def unchanged(a: str, b: str, path: str) -> bool:
    """True if ``path`` is identical at commits ``a`` and ``b``."""
    return not subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--quiet", a, b, "--", path]
    ).returncode


def blind_test() -> tuple[list[str], dict[str, list[str]], bool]:
    """The §7.9 criteria table, the blind-test phrases, and whether the failure was safe.

    Everything is re-derived from corpus/blind/task06_scheduler/results.json
    and its ground_truth.json; nothing is typed.
    """
    runs = list(json.loads((BLIND / "results.json").read_text()).values())
    truth = json.loads((BLIND / "ground_truth.json").read_text())
    site_files = sorted({s["file"] for s in truth["call_sites"]})
    n = len(runs)

    def across(values: list[str]) -> str:
        return f"{values[0]} ×{n}" if len(set(values)) == 1 else " / ".join(values)

    def hidden(r: dict[str, Any]) -> tuple[int, int]:
        h = r["hidden_semantic"]
        count = lambda word: int(m.group(1)) if (m := re.search(rf"(\d+) {word}", h)) else 0  # noqa: E731
        return count("failed"), count("passed")

    def attempts(r: dict[str, Any]) -> int:
        return max(a["attempt"] for a in r["correct_attempts"])

    no_wrong_edit = all(r["patch_files"] == site_files and not r["report_py_edited"] for r in runs)
    rows = [
        (
            "verdict GREEN",
            all(r["verdict"] == "GREEN" for r in runs),
            across([r["verdict"] for r in runs]),
        ),
        (
            "M1 recall and precision 100 %, decoys untouched",
            all(r["m1_recall"] == r["m1_precision"] == 100 and r["decoys_untouched"] for r in runs),
            across(
                [
                    f"M1 {r['m1_recall']:g}/{r['m1_precision']:g}, decoys "
                    f"{'byte-identical' if r['decoys_untouched'] else 'edited'}"
                    for r in runs
                ]
            ),
        ),
        (
            "M2 100 %, 0 regressions, hidden semantic tests pass",
            all(
                r["m2_pass_rate"] == 100 and not r["m2_regressions"] and not hidden(r)[0]
                for r in runs
            ),
            across(
                [
                    f"M2 {r['m2_pass_rate']:g}, {r['m2_regressions']} regr, "
                    f"hidden {hidden(r)[1]}/{sum(hidden(r))}"
                    for r in runs
                ]
            ),
        ),
        (
            "EPOCH fix made by the model",
            all(r["epoch_changed"] and r["recover_tokens"] > 0 for r in runs),
            across(
                [
                    f"EPOCH {'changed' if r['epoch_changed'] else 'unchanged'}, "
                    f"recover tokens {r['recover_tokens']}"
                    for r in runs
                ]
            ),
        ),
        (
            "clock.py gains `timezone`, config.py no import",
            all(r["clock_gained_timezone"] and r["config_import_lines_unchanged"] for r in runs),
            across(
                [
                    f"timezone {'added' if r['clock_gained_timezone'] else 'missing'}, config "
                    f"imports {'unchanged' if r['config_import_lines_unchanged'] else 'changed'}"
                    for r in runs
                ]
            ),
        ),
        (
            "patch touches only clock.py and config.py",
            no_wrong_edit,
            across(
                [
                    f"{len(r['patch_files'])} files, report.py "
                    f"{'edited' if r['report_py_edited'] else 'untouched'}"
                    for r in runs
                ]
            ),
        ),
        (
            "test files untouched",
            all(r["tests_untouched"] for r in runs),
            across(["byte-identical" if r["tests_untouched"] else "edited" for r in runs]),
        ),
        (
            "re-run on own output: empty patch, GREEN, 0 model calls",
            all(
                r["rerun"]["verdict"] == "GREEN"
                and r["rerun"]["patch_empty"]
                and not r["rerun"]["model_calls"]
                for r in runs
            ),
            across(
                [
                    f"{r['rerun']['verdict']}, patch "
                    f"{'empty' if r['rerun']['patch_empty'] else 'non-empty'}, "
                    f"{r['rerun']['model_calls']} calls"
                    for r in runs
                ]
            ),
        ),
        (
            "corrections ≤ 3; tokens and requests reported",
            all(r["corrections"] <= 3 for r in runs),
            f"corrections {across([str(r['corrections']) for r in runs])}; tokens "
            f"{' / '.join(str(r['tokens']) for r in runs)}; "
            f"requests {across([str(r['requests']) for r in runs])}",
        ),
    ]
    table = [BLIND_HEADER, "|---|---|---|---|"] + [
        f"| {i} | {name} | {'PASS' if ok else '**FAIL**'} | {evidence} |"
        for i, (name, ok, evidence) in enumerate(rows, 1)
    ]

    red = sum(r["verdict"] == "RED" for r in runs)
    cap = max(attempts(r) for r in runs)
    safe = (
        red == n
        and no_wrong_edit
        and all(r["tests_untouched"] for r in runs)
        and all(not a["changed"] for r in runs for a in r["correct_attempts"])
        and cap <= 3
    )
    passed = sum(ok for _, ok, _ in rows)
    frozen = unchanged(FROZEN_AT, BLIND_COMMIT, "src/")
    phrases = {
        "§4.5 blind corpus": [
            f"**|A| = {len(truth['call_sites'])}**",
            f"`src/mra/` frozen at `{FROZEN_AT}`"
            if frozen
            else f"<src/ changed between {FROZEN_AT} and {BLIND_COMMIT}>",
        ],
        "§7.9 blind results": [
            f"RED on **{red} of {n}** runs",
            f"{passed} of {len(rows)} criteria",
            f"recover tokens {runs[0]['recover_tokens']}",
        ],
        "§8.2 consequence break": [
            f"{cap} attempts",
            f"all {n} runs",
        ],
    }
    return table, phrases, safe


def blind07() -> dict[str, list[str]]:
    """§4.6/§7.10 phrases, the nine RESULTS.md criteria re-derived from task07's results.json."""
    runs = list(json.loads((BLIND07 / "results.json").read_text()).values())
    truth = json.loads((BLIND07 / "ground_truth.json").read_text())
    sites = {s["file"] for s in truth["call_sites"]}
    criteria = [
        lambda r: r["verdict"] == "GREEN" and not r["reasons"],
        lambda r: r["m1_recall"] == r["m1_precision"] == 100 and r["decoy_untouched"],
        lambda r: (
            r["m2_pass_rate"] == 100
            and not r["m2_regressions"]
            and not r["hidden_failures"]
            and r["hidden_semantic"].endswith("passed")
        ),
        lambda r: r["store_changed"] and r["recover_tokens"] > 0,
        lambda r: all(r["imports_unchanged"].values()),
        lambda r: set(r["patch_files"]) == sites | {"src/svc/store.py"},
        lambda r: r["tests_untouched"],
        lambda r: (
            r["rerun"]["verdict"] == "GREEN"
            and r["rerun"]["patch_empty"]
            and not r["rerun"]["model_calls"]
        ),
        lambda r: len(r["corrections"]) <= 3,
    ]
    met = {sum(c(r) for c in criteria) for r in runs}
    green, n = sum(r["verdict"] == "GREEN" for r in runs), len(runs)
    (corrections,) = {len(r["corrections"]) for r in runs}
    (hidden,) = {r["hidden_semantic"].split()[0] for r in runs}
    (version,) = {r["agent_version"] for r in runs}
    frozen = unchanged(FROZEN07_AT, BLIND07_COMMIT, "src/")
    return {
        "§4.6 second blind corpus": [
            f"**|A| = {len(truth['call_sites'])}**",
            f"`src/` frozen at `{FROZEN07_AT}`"
            if frozen
            else f"<src/ changed between {FROZEN07_AT} and {BLIND07_COMMIT}>",
            f"recorded the result, `{BLIND07_COMMIT}`",
        ],
        "§7.10 second blind results": [
            f"The agent at v{version}",
            f"GREEN on **{green} of {n}** runs",
            f"meets {min(met)} of {len(criteria)} criteria on every run",
            f"in {corrections} correction per run",
            f"passes {hidden} on it",
            f"Tokens per run were {' / '.join(str(r['tokens']) for r in runs)}",
            f"spent {' / '.join(str(r['recover_tokens']) for r in runs)}",
        ],
    }


def evidence_claims() -> dict[str, list[str]]:
    """§7.10 gold-check and import-accuracy phrases, counted from GOLD_CHECK.md's tables."""
    text = GOLD_CHECK_MD.read_text()
    gold = [
        cells(r)
        for r in table_after(
            text.split("\n"),
            text.split("\n")[
                next(
                    i
                    for i, line in enumerate(text.split("\n"))
                    if line.startswith("| run | task | files")
                )
            ],
        )[2:]
    ]
    clean = sum(row[-1] == "clean" for row in gold)
    planted = text.count(": flagged")
    imports_header = "| run | task | imports | expected | spurious | missing |"
    scored = [cells(r) for r in table_after(text.split("\n"), imports_header)[2:]]
    scored = [row for row in scored if row[2].endswith("%")]
    perfect = [row for row in scored if row[2] == "100.0%"]
    (worst,) = [row for row in scored if row[2] != "100.0%"]
    return {
        "§7.10 gold check": [
            f"**{clean} of {len(gold)}** are clean",
            f"the {sum('blind07' not in r[0] for r in gold)} ablation-E runs",
            f"the {sum('blind07' in r[0] for r in gold)} `task07` runs",
            f"{'Four' if planted == 4 else planted} faults planted",
        ],
        "§7.10 import accuracy": [
            f"Of the {len(scored)} scorable runs",
            f"**{len(perfect)} of {len(scored)}** score 100 %",
            f"warm r{worst[0].split('-r')[1][0]}, at {float(worst[2][:-1]):g} %",
        ],
    }


def bug_hunt(lines: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """§8.3/§9 phrases from BUGS.md, and every way the open list disagrees with tests/hunt."""
    text = BUGS_MD.read_text()
    table = [
        cells(r)
        for r in table_after(
            text.split("\n"), "| ID | Category | Severity | Reproduction | Expected vs actual |"
        )[2:]
    ]
    severity = {row[0]: row[2] for row in table}
    fixed = set(re.findall(r"^\* \*\*(BUG-\d+)\*\* \(v0\.4\.0\)", text, re.M))
    marked = {
        m
        for f in HUNT.glob("*.py")
        for m in re.findall(r'bug\(\s*"(BUG-\d+)"', f.read_text())
        + re.findall(r'\(\s*"(BUG-\d+)",\s*"', f.read_text())
    }
    open_ = sorted(set(severity) - fixed)
    count = lambda level, ids: sum(severity[i] == level for i in ids)  # noqa: E731
    severe = [i for i in severity if severity[i] in ("critical", "high")]
    problems = [f"{i} is open in BUGS.md but has no strict xfail" for i in open_ if i not in marked]
    problems += [
        f"{i} has a strict xfail but BUGS.md lists it fixed" for i in sorted(marked - set(open_))
    ]
    problems += [f"{i} ({severity[i]}) is not fixed" for i in severe if i not in fixed]
    a, b = section(lines, "# 9. Limitations", "# 10. Conclusion")
    item = " ".join(lines[a:b])
    item = item[item.index("**Open bugs.**") : item.index("**Report size.**")]
    listed = sorted(set(re.findall(r"BUG-\d+", item)))
    if listed != open_:
        problems.append(f"§9 open-bug list {listed} != BUGS.md open {open_}")
    levels = ("critical", "high", "medium", "low")
    rerun = re.search(r"payload identical \((\d+)/(\d+)\)", text)
    return {
        "§8.3 bug hunt": [
            f"found **{len(severity)}** bugs: "
            + ", ".join(f"{count(lv, severity)} {lv}" for lv in levels[:3])
            + f" and {count('low', severity)} low",
            f"**All {len(severe)} critical and high bugs are fixed in",
            f"{count('medium', open_)} medium and {count('low', open_)} low remain open",
            f"`{RESULTS_COMMIT}`"
            if unchanged(RESULTS_COMMIT, "HEAD", "runs/benchmark/results.json")
            else f"<results.json changed since {RESULTS_COMMIT}>",
            f"{rerun.group(1)} of {rerun.group(2)} rows"
            if rerun
            else "<no matrix re-run in BUGS.md>",
        ],
        "§8.3 silent check": [
            "`test_ctrl_c_mid_batch`"
            if "vacuous" in commit_message(SILENT_CHECK_COMMIT)
            and 'f"name=^mra-{intr}-"' in (HUNT / "test_env_faults.py").read_text()
            else "<the leftover filter is not the fixed one>",
            f"commit {SILENT_CHECK_COMMIT}",
        ],
        "§9 open bugs": [
            f"{count('medium', open_)} medium and {count('low', open_)} low are open",
        ],
    }, problems


def main() -> int:
    paper = PAPER.read_text()
    lines = paper.split("\n")

    # 1. §7.1 is spliced from results.md §1, not transcribed. Prove it.
    src_grid = table_after(RESULTS_MD.read_text().split("\n"), GRID_HEADER)
    paper_grid = table_after(lines, GRID_HEADER)
    check(
        src_grid == paper_grid,
        f"§7.1 grid is byte-identical to results.md §1 ({len(src_grid) - 2} data rows)",
    )

    # 2. Provenance: no numeric span in a fact-assembled section may close
    #    without a SOURCE pointer.
    for name, start, end, is_claim in (
        ("Abstract", "# Abstract", "# 1. Introduction", states_a_count),
        ("§3", "# 3. System", "# 4. Corpus", carries_a_figure),
        ("§4", "# 4. Corpus", "# 5. Metrics", carries_a_figure),
        ("§7", "# 7. Results", "# 8. Failure", carries_a_figure),
        ("§8", "# 8. Failure", "# 9. Limitations", carries_a_figure),
        ("§9", "# 9. Limitations", "# 10. Conclusion", carries_a_figure),
    ):
        pointers, gaps = uncovered_spans(lines, *section(lines, start, end), is_claim)
        check(
            not gaps, f"{name}: every numeric span closed by a SOURCE pointer ({pointers} pointers)"
        )
        for gap in gaps:
            print(f"    uncovered -> {gap}")

    # 3. §8 counts are re-derived, never typed.
    failures = FAILURES_MD.read_text()
    pairs = failures.count("\n## `")
    behaviour = failures.count("**behaviour** break")
    disabled = failures.count("why it was not recovered:** recovery disabled")
    check(
        "42 of 165 runs failed" in failures and "42 did not reach green" in paper,
        "§8: 42 of 165 runs failed",
    )
    check(pairs == 14 and "14 distinct" in paper, f"§8: {pairs} distinct (config, task) pairs")
    check(
        behaviour == 26 and "all 26 surviving failures" in paper,
        f"§8: {behaviour}/{behaviour} surviving failures classify as behaviour",
    )
    check(disabled == pairs, f"§8: all {pairs} pairs cite a disabled loop, not an exhausted one")

    # 4. The retry-cap claim, straight from the run records.
    data = json.loads(RESULTS_JSON.read_text())
    rows = data["rows"]
    peak = lambda r: max((r.get("fix_attempts") or {"_": 0}).values())  # noqa: E731
    at_cap = sorted({(r["config"], r["task_id"], r["outcome"]) for r in rows if peak(r) == 3})
    exhausted = [r for r in rows if r["outcome"] == "gave_up" and peak(r) >= 3]
    check(
        max(peak(r) for r in rows) == 3 and not exhausted,
        "§8: no run gave up by exhausting MAX_FIX_ATTEMPTS = 3",
    )
    check(
        len(at_cap) == 2 and all(o == "success" for _, _, o in at_cap),
        f"§8: the cap is reached only by {', '.join(c for c, _, _ in at_cap)} — both green",
    )
    check(
        len(rows) == 165 and len(data["skipped"]) == 10,
        "§6/§7.6: 165 offline rows, 10 pairs skipped for want of a key",
    )

    # 5. The prose sections stay stubs, and §2 invents no citation.
    # The Abstract and §1 are written, so they are checked for what they must NOT contain.
    for heading in (
        "# 2. Related Work",
        "# 10. Conclusion",
        "# References",
    ):
        body = "\n".join(lines[lines.index(heading) : lines.index(heading) + 6])
        check("STUB" in body, f"stub preserved: {heading.lstrip('# ')}")
    for name, start, end in (
        ("Abstract", "# Abstract", "# 1. Introduction"),
        ("§1", "# 1. Introduction", "# 2. Related Work"),
    ):
        a, b = section(lines, start, end)
        body = "\n".join(lines[a:b])
        check("STUB" not in body, f"{name}: written — the stub outline is gone")
        padding = sorted(set(re.findall(INTENSIFIERS, body, re.IGNORECASE)))
        found = f" — found {', '.join(padding)}" if padding else ""
        check(not padding, f"{name}: no intensifier padding{found}")
    lit_start, lit_end = section(lines, "# 2. Related Work", "# 3. System")
    related = "\n".join(lines[lit_start:lit_end])
    check(
        related.count("[CITE:") == 9,
        f"§2: {related.count('[CITE:')} unresolved [CITE:] placeholders",
    )
    check(
        not re.search(r"\n\[\d+\]\s|\n- [A-Z][a-z]+,\s+[A-Z]\.", paper),
        "§2/References: no reference filled in yet, so none can be fabricated",
    )

    # 6. RESULTS_SUMMARY.md is hand-written, paper-cited and regenerated by
    #    nothing. Re-derive every table cell from results.json so a rerun that
    #    moves a number cannot leave the summary quietly behind.
    slines = SUMMARY_MD.read_text().split("\n")
    agg = {(a["config"], a["task_id"]): a for a in data["aggregates"]}
    base = {b["task_id"]: b for b in data["baselines"]}
    drift: list[str] = []
    claims = 0

    def derived(config: str, task: str) -> dict[str, Any]:
        a = agg[(config, task)]
        return {
            "repeats": a["n"],
            "outcomes": a["outcomes"],
            "m1": round(a["m1_recall_mean"]),
            "m2": round(a["m2_pass_rate_mean"], 1),
            "regr": round(a["m2_regressions_mean"]),
            "corr": round(a["corrections_mean"]),
        }

    def verify_cell(cell: str, exp: dict[str, Any], where: str) -> None:
        """Every figure in `cell` must match `exp`; none may go unread."""
        nonlocal claims
        rest = cell
        for name, pattern in CELL_FIGURES:
            m = pattern.search(cell)
            if m is None:
                continue
            rest = rest.replace(m.group(0), " ", 1)
            claims += 1
            if float(m.group(1)) != float(exp[name]):
                drift.append(f"{where}: {name} reads {m.group(1)}, results.json has {exp[name]}")
        for word in ("gave_up", "success"):
            if word in cell:
                rest = rest.replace(word, " ")
                claims += 1
                if list(exp["outcomes"]) != [word]:
                    drift.append(
                        f"{where}: outcome reads {word}, results.json has {exp['outcomes']}"
                    )
        if re.search(r"\d", re.sub(r"task\d\w*|M[12]", "", rest)):
            drift.append(f"{where}: figure not covered by the check -> {cell!r}")

    def task_of(label: str) -> str:
        return re.search(r"task\d\w*", label).group(0)

    # (a) baseline vs no-recovery, and (c) the two ablation-B tables.
    for row in tables_after(slines, LOOP_HEADER)[0]:
        col = cells(row)
        task = task_of(col[0])
        for cell, config in zip(col[1:], ("baseline", "no-recovery"), strict=True):
            verify_cell(cell, derived(config, task), f"(a) {task}/{config}")
    order_tables = tables_after(slines, ORDER_HEADER)
    for row in order_tables[0]:
        col = cells(row)
        task = task_of(col[0])
        for cell, config in zip(col[1:], ORDER_CONFIGS[0], strict=True):
            verify_cell(cell, derived(config, task), f"(c1) {task}/{config}")
    for row in order_tables[1]:
        col = cells(row)
        task = task_of(col[0])
        for cell, config in zip(col[1:], ORDER_CONFIGS[1], strict=True):
            # This table reports mean corrective edits and nothing else.
            claims += 1
            edits = derived(config, task)["corr"]
            if figures(cell) != [float(edits)]:
                drift.append(
                    f"(c2) {task}/{config}: reads {cell!r}, "
                    f"results.json has {edits} corrective edit(s)"
                )

    # (b) the deterministic baselines, straight from results.json["baselines"].
    for row in tables_after(slines, BASELINE_HEADER)[0]:
        col = cells(row)
        task = task_of(col[0])
        tools = {t["tool"]: t for t in base[task]["tools"]}
        ruff, pyup = tools["ruff (DTZ)"], tools["pyupgrade"]
        want: list[tuple[str, list[float] | str]] = [
            ("|A|", [float(base[task]["ground_truth_sites"])]),
            ("ruff fixed", [float(ruff["fixed_files"])]),
            ("M1 after fix", [round(ruff["m1_recall_after_fix"])]),
            ("suite after fix", ruff["suite_after_fix"]),
            ("pyupgrade detected", [float(pyup["detected"]), round(pyup["detect_recall"])]),
        ]
        detected = [float(ruff["detected"]), round(ruff["detect_recall"])]
        claims += 1
        if figures(col[2]) not in (detected, detected + [round(ruff["detect_precision"])]):
            drift.append(
                f"(b) {task}/ruff detected: reads {col[2]!r}, results.json has "
                f"detected {ruff['detected']}, recall {ruff['detect_recall']}, "
                f"precision {ruff['detect_precision']}"
            )
        plain = (col[1], col[3], col[4], col[5], col[6])
        for (name, expected), cell in zip(want, plain, strict=True):
            claims += 1
            got = cell if isinstance(expected, str) else figures(cell)
            if got != expected:
                drift.append(f"(b) {task}/{name}: reads {cell!r}, results.json has {expected}")

    # The header's provenance line and its arithmetic.
    head = "\n".join(slines[:12])
    stamp = re.search(r"generated (\S+?)Z", head)
    claims += 1
    if stamp is None or stamp.group(1)[:19] != data["generated_at"][:19]:
        drift.append(
            f"header: generated stamp is {stamp and stamp.group(1)}, "
            f"results.json was generated {data['generated_at'][:19]}"
        )
    matrix = re.search(
        r"(\d+) tasks × (\d+) offline\s+configurations × (\d+) "
        r"repeats = (\d+) runs",
        head,
    )
    claims += 1
    counted = (len(data["tasks"]), len({r["config"] for r in rows}), data["repeats"], len(rows))
    if matrix is None or tuple(int(g) for g in matrix.groups()) != counted:
        drift.append(
            f"header: matrix reads {matrix and matrix.groups()}, results.json has {counted}"
        )

    # The two prose figures no table restates.
    gave_up = sum(
        1 for t in data["tasks"] if list(agg[("no-recovery", t)]["outcomes"]) == ["gave_up"]
    )
    claims += 1
    if f"{gave_up} of the {len(data['tasks'])} Tier-A tasks end in" not in "\n".join(slines):
        drift.append(
            f"(a) prose: results.json has {gave_up} of {len(data['tasks'])} "
            f"tasks ending in gave_up without the loop"
        )
    dependents_first = [
        r
        for r in rows
        if r["config"] == "order-fr3-violating-b1" and r["task_id"] == "task04_multimodule"
    ]
    ceiling = max(peak(r) for r in dependents_first)
    claims += 1
    if f"retry ceiling of {ceiling} attempts" not in "\n".join(slines):
        drift.append(f"(c2) prose: the dependents-first task04 arm peaks at {ceiling} fix attempts")

    check(not drift, f"RESULTS_SUMMARY.md: {claims} figures re-derived from results.json")
    for item in drift:
        print(f"    drift -> {item}")

    # 7. Post-P5 additions (§3.6, §4.4, §7.7, §7.8, §8.1, §9.6), each figure
    #    re-derived from the file or commit its SOURCE pointer names.
    flat = " ".join(paper.split())
    e_paper = table_after(lines, E_HEADER)
    check(
        e_paper == table_after(ABLATION_E_MD.read_text().split("\n"), E_HEADER),
        f"§7.8 ablation E table byte-identical to its results.md ({len(e_paper) - 2} rows)",
    )
    defects, unpinned = pinned_defects(lines)
    check(not unpinned, f"§8.1: {defects} defects, each row names a regression test in tests/")
    for item in unpinned:
        print(f"    no such test -> {item}")
    for label, claims_ in post_p5_claims(data, defects).items():
        missing = [c for c in claims_ if c not in flat]
        check(not missing, f"{label}: {len(claims_)} figures re-derived")
        for c in missing:
            print(f"    expected in paper -> {c!r}")

    # 8. The blind held-out task: §7.9's table is regenerated from its
    #    results.json and must match byte for byte; the safe-failure claim
    #    (§8.2) is re-derived, not asserted.
    table, blind_phrases, safe = blind_test()
    paper_table = table_after(lines, BLIND_HEADER) if BLIND_HEADER in lines else []
    check(paper_table == table, f"§7.9 blind criteria table re-derived ({len(table) - 2} rows)")
    if paper_table != table:
        print("    expected table ->\n" + "\n".join(table))
    check(
        safe and "The failure was safe." in flat,
        "§8.2: the blind failure was safe (RED, no wrong edit, tests untouched, capped)",
    )
    for label, claims_ in blind_phrases.items():
        missing = [c for c in claims_ if c not in flat]
        check(not missing, f"{label}: {len(claims_)} figures re-derived")
        for c in missing:
            print(f"    expected in paper -> {c!r}")
    # 9. v0.4.0 additions: the second blind task, the live evidence, the bug hunt.
    hunt, problems = bug_hunt(lines)
    check(
        not problems, "§8.3/§9: open bugs = BUGS.md minus fixed = the strict xfails in tests/hunt"
    )
    for item in problems:
        print(f"    bug list -> {item}")
    for label, claims_ in {**blind07(), **evidence_claims(), **hunt}.items():
        missing = [c for c in claims_ if c not in flat]
        check(not missing, f"{label}: {len(claims_)} figures re-derived")
        for c in missing:
            print(f"    expected in paper -> {c!r}")
    version = re.search(r'^version = "(.+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    check(
        f"in v{version}" in flat, f"§3/§8.3: the fixes are credited to v{version} (pyproject.toml)"
    )

    scoped = "residual call sites"
    for name, text in (
        ("Abstract", "\n".join(lines[slice(*section(lines, "# Abstract", "# 1. Intro"))])),
        ("§1", "\n".join(lines[slice(*section(lines, "# 1. Intro", "# 2. Related"))])),
        ("§7", "\n".join(lines[slice(*section(lines, "# 7. Results", "# 8. Failure"))])),
        ("§9", "\n".join(lines[slice(*section(lines, "# 9. Limit", "# 10. Concl"))])),
        ("RESULTS_SUMMARY", "\n".join(slines)),
    ):
        check(scoped in " ".join(text.split()), f"{name}: recovery claim scoped to {scoped}")

    width = max(len(m) for _, m in results)
    for passed, message in results:
        print(f"{'PASS' if passed else 'FAIL'}  {message.ljust(width)}")
    failed = sum(1 for passed, _ in results if not passed)
    print(f"\n{len(results) - failed}/{len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
