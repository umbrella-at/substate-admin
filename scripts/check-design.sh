#!/usr/bin/env bash
#
# The rules docs/design.md says the build enforces. Each of these is a rule a person would
# otherwise have to remember, on a diff nobody is required to read.
#
# Run it exactly as CI does:  ./scripts/check-design.sh
# It needs frontend/dist, so run `npm run build` in frontend/ first.

set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

failures=0
fail() { echo "::error file=$1::$2"; failures=$((failures + 1)); }
ok() { printf '    ok    %s\n' "$1"; }

echo "the round shape:"
# `rounded-full` survives a cleared --radius-* namespace, because Tailwind ships it as a static
# utility rather than deriving it from the theme. design.md reserves the 999px shape for the five
# subscription states, and the natural place to break that is the first avatar somebody adds.
readonly STATE_CHIP='frontend/src/components/StateChip.vue'
offenders="$(grep -rln --include='*.vue' --include='*.ts' -e 'rounded-full' -e 'rounded-chip' \
    frontend/src | grep -v "^${STATE_CHIP}$" || true)"
if [ -n "$offenders" ]; then
    while IFS= read -r file; do
        fail "$file" "rounded-full/rounded-chip outside the state chip; docs/design.md reserves the round shape for the five subscription states"
    done <<<"$offenders"
else
    ok "the 999px shape appears only where design.md allows it"
fi

echo "the fonts:"
# Declared as a dependency and imported nowhere is a silent failure: the fallback stack renders,
# nothing looks broken, and the whole typography section is quietly unimplemented. No other check
# can see the difference, because there is nothing to see.
css="$(find frontend/dist/assets -name '*.css' 2>/dev/null | head -1)"
if [ -z "$css" ]; then
    fail "frontend/dist" "no built CSS found; run npm run build in frontend/ before this check"
else
    faces="$(grep -o '@font-face' "$css" | wc -l | tr -d ' ')"
    files="$(find frontend/dist/assets -name '*.woff2' | wc -l | tr -d ' ')"
    # Two families, two weights each.
    if [ "$faces" -eq 4 ] && [ "$files" -ge 4 ]; then
        ok "$faces @font-face rules and $files woff2 files shipped"
    else
        fail "frontend/src/styles/tokens.css" "expected 4 @font-face rules and at least 4 woff2 files in the build, found $faces and $files"
    fi
fi

echo "the palette:"
python3 scripts/contrast.py > /tmp/contrast.txt 2>&1 && contrast_ok=1 || contrast_ok=0
if [ "$contrast_ok" = 1 ]; then
    ok "every pair the requirement applies to holds"
else
    tail -n 6 /tmp/contrast.txt | sed 's/^/    /'
    fail "docs/design.md" "a colour pair is below its contrast requirement; see the run above"
fi

echo
if [ "$failures" -gt 0 ]; then
    echo "$failures problem(s) found"
    exit 1
fi
echo "design rules hold"
