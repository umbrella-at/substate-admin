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

echo "comment blocks:"
# Decision 166 put a ceiling on a comment and nothing made it hold, so the code written after it
# does not. `comments.py` parses rather than matches, because a `#` in a URL is not a comment.
if python3 scripts/comments.py; then
    :
else
    failures=$((failures + 1))
fi

echo "the round shape:"
# `rounded-full` survives a cleared --radius-* namespace, because Tailwind ships it as a static
# utility rather than deriving it from the theme. design.md reserves the 999px shape for the five
# subscription states, and the natural place to break that is the first avatar somebody adds.
readonly STATE_CHIP='frontend/src/components/StateChip.vue'
#
# Spec files are excluded. The rule is about what gets rendered, and a test does not render — but
# it does write class names down, in fixtures and in comments explaining this very rule, and a
# check that makes somebody reword a sentence to get past it is a check they will reword the rule
# to get past next.
offenders="$(grep -rln --include='*.vue' --include='*.ts' -e 'rounded-full' -e 'rounded-chip' \
    frontend/src | grep -v "^${STATE_CHIP}$" | grep -v '\.spec\.ts$' || true)"
if [ -n "$offenders" ]; then
    while IFS= read -r file; do
        fail "$file" "rounded-full/rounded-chip outside the state chip; docs/design.md reserves the round shape for the five subscription states"
    done <<<"$offenders"
else
    ok "the 999px shape appears only where design.md allows it"
fi

css="$(find frontend/dist/assets -name '*.css' 2>/dev/null | head -1)"
# Two of the checks below read the build rather than the source, which makes them quietly wrong
# when the build is older than the file they are judging: a utility written a minute ago is absent
# from last hour's CSS, and the failure names the utility rather than the reason. CI builds
# immediately before running this, so this only ever fires for someone running it by hand.
if [ -n "$css" ] && [ -n "$(find frontend/src -newer "$css" -type f -print -quit)" ]; then
    fail "frontend/dist" "the build is older than frontend/src; run npm run build before this check, or the font and radius rules judge stale CSS"
fi

echo "utilities that compile to nothing:"
# The other half of a closed namespace, and the reasoning is in scripts/utilities.py. In short: a
# utility asking for a step this project does not define produces no CSS at all, silently, and the
# element renders with square corners or with no height while the source looks right.
if [ -z "$css" ]; then
    : # already reported by the staleness guard
elif python3 scripts/utilities.py "$css"; then
    ok "every utility written in the markup produces a rule"
else
    failures=$((failures + 1))
fi

echo "what the stylesheet loads:"
# Everything it loads has to be next to it, and the reasoning is in scripts/assets.py. In short:
# the generator writes a Google Fonts @import, the CSP refuses it, the page renders on the fallback
# stack, and the @font-face count below stays green because a remote import contributes none.
if [ -z "$css" ]; then
    : # already reported by the staleness guard
elif python3 scripts/assets.py "$css"; then
    ok "every asset the stylesheet loads is served from this origin"
else
    failures=$((failures + 1))
fi

echo "the fonts:"
# Declared as a dependency and imported nowhere is a silent failure: the fallback stack renders,
# nothing looks broken, and the whole typography section is quietly unimplemented. No other check
# can see the difference, because there is nothing to see.
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

echo "one palette:"
# Adding a shadcn component re-runs a generator that writes colour values, and its instinct is to
# put a full light-and-dark palette back into the stylesheet. Nothing would look wrong: the second
# palette would win in the components using it, design.md would still describe the first, and the
# two would drift apart with no diff anybody is obliged to read. So every colour a utility can
# reach has to be defined in the one file the design document describes.
readonly TOKENS='frontend/src/styles/tokens.css'
strays="$(grep -rln --include='*.css' -e '--color-' frontend/src | grep -v "^${TOKENS}$" || true)"
if [ -n "$strays" ]; then
    while IFS= read -r file; do
        fail "$file" "--color-* defined outside $TOKENS; docs/design.md is the only palette"
    done <<<"$strays"
fi
# The shadcn vocabulary must be aliases, not values. A generator writing `--color-primary:
# oklch(...)` into the alias block would be a colour the design document does not know about,
# whatever it happens to be set to today, and it would look exactly like the line next to it.
literals="$(awk '/^@theme inline \{/{inside=1; next} inside && /^\}/{inside=0} inside' "$TOKENS" \
    | grep -nE -- '--[a-z0-9-]+:\s*(#|oklch|rgb|hsl|[0-9])' || true)"
if [ -n "$literals" ]; then
    while IFS= read -r line; do
        fail "$TOKENS" "the shadcn alias block must alias, not define: ${line#*:}"
    done <<<"$literals"
fi
if [ -z "$strays" ] && [ -z "$literals" ]; then
    ok "every colour a utility can reach is defined in $TOKENS"
fi

echo "colours a canvas is handed:"
# A chart library takes colours as JavaScript values, so a hex in a chart config is not a utility,
# not a cleared namespace and not a `--color-*` definition — it passes every check above.
if python3 scripts/colours.py; then
    :
else
    failures=$((failures + 1))
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
