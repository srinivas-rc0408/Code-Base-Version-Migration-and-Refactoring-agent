# Gold check — live and blind07 runs

Final migrated trees (`../File1/runs/`) compared against each task's `gold/` with
`python scripts/gold_check.py ../File1/runs --self-test`. Trees are not archived; each run's
`migration.patch` plus `metrics.json` (benchmark runs, which build no report) or `report.json`
(blind07 runs) is, under `evidence/<run_id>/`.

**Result: 36 runs, 36 clean.** No source file shorter than gold, no gold function or class
missing, no hunk outside call sites, gold-changed (consequence) lines or imports; tests and
config byte-identical to `old/`.

| run | task | files differing from gold | missing definitions | verdict |
|---|---|---|---|---|
| memory-off-llm-task01_datetime-r0-432dc2 | task01_datetime | 0 | 0 | clean |
| memory-off-llm-task01_datetime-r1-32e9ec | task01_datetime | 0 | 0 | clean |
| memory-off-llm-task01_datetime-r2-72aa92 | task01_datetime | 0 | 0 | clean |
| memory-off-llm-task02_datetime_aliased-r0-f6e292 | task02_datetime_aliased | 0 | 0 | clean |
| memory-off-llm-task02_datetime_aliased-r1-1ca133 | task02_datetime_aliased | 0 | 0 | clean |
| memory-off-llm-task02_datetime_aliased-r2-cdc1f3 | task02_datetime_aliased | 0 | 0 | clean |
| memory-off-llm-task03_half_migration-r0-20dbf9 | task03_half_migration | 0 | 0 | clean |
| memory-off-llm-task03_half_migration-r1-b70ac4 | task03_half_migration | 0 | 0 | clean |
| memory-off-llm-task03_half_migration-r2-38fa2f | task03_half_migration | 0 | 0 | clean |
| memory-off-llm-task04_multimodule-r0-d0f4f0 | task04_multimodule | 0 | 0 | clean |
| memory-off-llm-task04_multimodule-r1-9cccb5 | task04_multimodule | 0 | 0 | clean |
| memory-off-llm-task04_multimodule-r2-5e9cc8 | task04_multimodule | 0 | 0 | clean |
| memory-off-llm-task05_signature_break-r0-f2595a | task05_signature_break | 0 | 0 | clean |
| memory-off-llm-task05_signature_break-r1-04f924 | task05_signature_break | 0 | 0 | clean |
| memory-off-llm-task05_signature_break-r2-9b5fe7 | task05_signature_break | 0 | 0 | clean |
| memory-warm-llm-task01_datetime-r0-00f10a | task01_datetime | 0 | 0 | clean |
| memory-warm-llm-task01_datetime-r1-62cb43 | task01_datetime | 0 | 0 | clean |
| memory-warm-llm-task01_datetime-r2-6bb8be | task01_datetime | 0 | 0 | clean |
| memory-warm-llm-task02_datetime_aliased-r0-83c48f | task02_datetime_aliased | 0 | 0 | clean |
| memory-warm-llm-task02_datetime_aliased-r1-f2d390 | task02_datetime_aliased | 1 (src/pkg/report.py) | 0 | clean |
| memory-warm-llm-task02_datetime_aliased-r2-567110 | task02_datetime_aliased | 0 | 0 | clean |
| memory-warm-llm-task03_half_migration-r0-c90daa | task03_half_migration | 0 | 0 | clean |
| memory-warm-llm-task03_half_migration-r1-d663d0 | task03_half_migration | 0 | 0 | clean |
| memory-warm-llm-task03_half_migration-r2-c3e8f2 | task03_half_migration | 0 | 0 | clean |
| memory-warm-llm-task04_multimodule-r0-ce0524 | task04_multimodule | 0 | 0 | clean |
| memory-warm-llm-task04_multimodule-r1-5b3e5d | task04_multimodule | 0 | 0 | clean |
| memory-warm-llm-task04_multimodule-r2-827736 | task04_multimodule | 0 | 0 | clean |
| memory-warm-llm-task05_signature_break-r0-abd3cf | task05_signature_break | 0 | 0 | clean |
| memory-warm-llm-task05_signature_break-r1-ed7454 | task05_signature_break | 0 | 0 | clean |
| memory-warm-llm-task05_signature_break-r2-5dab7d | task05_signature_break | 0 | 0 | clean |
| blind07-r1 | task07_cache | 0 | 0 | clean |
| blind07-r1-rerun | task07_cache | 0 | 0 | clean |
| blind07-r2 | task07_cache | 0 | 0 | clean |
| blind07-r2-rerun | task07_cache | 0 | 0 | clean |
| blind07-r3 | task07_cache | 0 | 0 | clean |
| blind07-r3-rerun | task07_cache | 0 | 0 | clean |


## Notes

- **task02 warm r1** (`memory-warm-llm-task02_datetime_aliased-r1-f2d390`) differs from gold in
  `src/pkg/report.py`: it adds `from datetime import timezone` and writes `timezone.utc` where
  gold uses `dt.timezone.utc`. Same migration, equivalent spelling; both edits are on the call
  site and an import line.
- **Did M1 precision count the redundant import? No.** `m1_precision` is 100.0 in the run's
  `metrics.json` and in `results_live.json`. M1 scores MAP's call sites keyed by
  `(file, line, col, symbol)` (`src/mra/graph.py`), so an import line is never a site. By the
  same construction M1 cannot see any non-call-site edit; the hunk check above covers that.
- Expected raw-text differences (not agent edits): gold-only tests, gold's `pyproject.toml`
  description, and docstrings gold rewrote.
- The three `-rerun` runs re-ran the agent on its own output; their patches are empty by design.

## Planted faults (the check is not blind)

- drop_last_def on memory-off-llm-task04_multimodule-r0-d0f4f0: flagged
- cut_tail on memory-off-llm-task04_multimodule-r0-d0f4f0: flagged
- stray_line on memory-off-llm-task04_multimodule-r0-d0f4f0: flagged
- edit_test on memory-off-llm-task04_multimodule-r0-d0f4f0: flagged
