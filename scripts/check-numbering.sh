#!/usr/bin/env bash
#
# No internal planning numbers anywhere a reader of this repository can see.
#
# The work is organised in numbered rounds in a document that lives outside the repository. Those
# numbers describe the order things were built in, which is of no use to anybody reading the code
# and actively misleading in a file that outlives the plan — "added in round two" tells a reader
# there is a round two to go and find, and there is not. State is described instead: what is true
# now, and what it is waiting on.
#
# This was a manual grep before it was a script, which is the same as saying it ran when somebody
# remembered. It caught a violation written in this repository by the person who wrote the rule.
#
# Run it exactly as CI does:  ./scripts/check-numbering.sh

set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Ordinals in both languages, digits, and the words that precede them. Deliberately broad: a false
# positive costs one line in the allow list below and a miss costs a number nobody notices again.
readonly PATTERN='(iteration|заход[ае]?|итерац[а-я]*|\bPR)[ -]*(one|two|three|four|five|[1-5]|перв|втор|трет|четв|пят)'

# Phrases that match the pattern and mean something else. Each is here because it was checked, not
# because it was convenient: a loop's last pass, a second uvicorn process, and a sentence in the
# README about this not being a second product.
readonly ALLOWED='last iteration|a second process|not a second product'

# Scanned through `git ls-files` rather than by walking the tree. The rule is about what this
# repository shows a reader, and a build directory is not that — the first version of this check
# walked the tree and reported a hundred hits inside a Playwright HTML report, which is generated,
# ignored, and not something anybody reads as our writing.
#
# This file is excluded from its own scan. It contains the pattern because it defines the pattern,
# the same way the state chip is the one file allowed to use the round shape.
readonly SELF='scripts/check-numbering.sh'

hits=''
while IFS= read -r -d '' file; do
    [ "$file" != "$SELF" ] || continue
    [ -f "$file" ] || continue
    match="$(grep -niE "$PATTERN" "$file" 2>/dev/null | grep -viE "$ALLOWED" || true)"
    [ -n "$match" ] || continue
    while IFS= read -r line; do
        hits="${hits}${file}:${line}"$'\n'
    done <<<"$match"
done < <(git ls-files -z)

if [ -n "$hits" ]; then
    while IFS= read -r hit; do
        [ -n "$hit" ] || continue
        file="${hit%%:*}"
        rest="${hit#*:}"
        line="${rest%%:*}"
        echo "::error file=${file},line=${line}::internal planning number in a repository file; describe the state instead — ${rest#*:}"
    done <<<"$hits"
    exit 1
fi

echo "    ok    no internal planning numbers in the repository"
