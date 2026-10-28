#!/usr/bin/env bash
# Hunt 8: mutation testing (mutmut) on the verdict, the planner, failure-signature
# normalisation and the provider key failover. Runs in a scratch copy so the
# checkout is untouched; a stub `docker` on PATH makes every docker test skip,
# so survivors are measured against the offline suite.
#   tests/hunt/mutation/run.sh            -> tests/hunt/mutation/survivors.txt
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
HERE="$ROOT/tests/hunt/mutation"
WORK=${MUTMUT_WORK:-$(mktemp -d)}
rsync -a --delete --exclude __pycache__ --exclude 'tests/hunt/fixtures' \
    "$ROOT/src" "$ROOT/tests" "$ROOT/corpus" "$ROOT/pyproject.toml" "$ROOT/mra.example.toml" "$WORK/"
cat "$HERE/mutmut.toml" >> "$WORK/pyproject.toml"
mkdir -p "$WORK/.fakebin"
printf '#!/bin/sh\nexit 1\n' > "$WORK/.fakebin/docker"
chmod +x "$WORK/.fakebin/docker"
cd "$WORK"
# The selected functions only: the rest of runner.py is docker plumbing.
SELECT=(
    "mra.verdict.*"
    "mra.nodes.plan_node.*"
    "mra.sandbox.runner.x_normalize_message*"
    "mra.sandbox.runner.x_failure_signature*"
    "mra.models.providers.base.*"
)
PATH="$WORK/.fakebin:$PATH" "$ROOT/.venv/bin/mutmut" run --max-children "${MUTMUT_CHILDREN:-8}" "${SELECT[@]}" || true
"$ROOT/.venv/bin/mutmut" results --all true > "$WORK/results.txt" 2>&1 || "$ROOT/.venv/bin/mutmut" results > "$WORK/results.txt" 2>&1
grep -E "survived|no tests|timeout|suspicious" "$WORK/results.txt" | grep -E "verdict|plan_node|normalize_message|failure_signature|providers\.base" > "$HERE/survivors.txt" || true
for name in $(awk -F: '{print $1}' "$HERE/survivors.txt"); do
    echo "=== $name"
    "$ROOT/.venv/bin/mutmut" show "$name" 2>/dev/null | sed -n '1,40p'
done > "$HERE/survivors_diff.txt"
echo "work dir: $WORK"
wc -l "$HERE/survivors.txt"
