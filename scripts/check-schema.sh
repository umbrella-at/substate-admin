#!/usr/bin/env bash
#
# The OpenAPI document and the frontend types generated from it still describe this backend.
#
# Both files are committed so that the frontend type check needs no running server: a generator
# that required the API to be up could not run in the job that decides whether the API is correct,
# and it would turn a type check into an integration test. The whole worth of a committed
# generated file is that it still describes its source, and this is what keeps that true — both
# are regenerated from scratch and any difference at all is a failure.
#
# THE DIFFERENCE MAY BE LAYOUT RATHER THAN CONTENT, AND THAT STILL FAILS ON PURPOSE.
#
# `app/openapi.py` writes with sorted keys and a trailing newline, so the bytes depend on the
# routes and on nothing else. A document produced another way — by hand, by a shell one-liner, by
# reading a running server — can describe exactly the same API and still not match, and the diff
# then reads as a thousand lines of moved routes rather than as reordering. That is the failure
# this check produced once, which is why regenerating is one command nobody has to reconstruct.
#
# WHAT IS COMPARED, AND WHY IT IS NOT THE INDEX.
#
# The files are copied aside, regenerated, and compared against the copies. Not against `git
# diff`, which compares the working tree with the index: in CI those are the same thing, but the
# gate runs BEFORE a commit, where a legitimately edited schema differs from the index and would
# fail a check that asked git. The invariant that means something in both places is the same one —
# what is on disk is what this backend produces.
#
# Run it exactly as CI does:  ./scripts/check-schema.sh

set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

readonly SCHEMA='backend/openapi.json'
readonly TYPES='frontend/src/api/schema.d.ts'

failures=0

# A generated file that git does not track is one nobody else ever receives. `git diff` is silent
# about it, so without this an untracked schema would pass as quietly as a matching one.
for file in "$SCHEMA" "$TYPES"; do
    if ! git ls-files --error-unmatch "$file" > /dev/null 2>&1; then
        echo "::error file=$file::not tracked by git; a generated file nobody commits is one nobody receives"
        failures=$((failures + 1))
    fi
done
[ "$failures" -eq 0 ] || exit 1

before="$(mktemp -d)"
trap 'rm -rf "$before"' EXIT
cp "$SCHEMA" "$before/openapi.json"
cp "$TYPES" "$before/schema.d.ts"

(cd backend && uv run --frozen python -m app.openapi > /dev/null)
(cd frontend && npm run types --silent > /dev/null)

if ! diff -q "$before/openapi.json" "$SCHEMA" > /dev/null; then
    echo "::error file=$SCHEMA::stale; this is not what the backend serves"
    failures=$((failures + 1))
fi

if ! diff -q "$before/schema.d.ts" "$TYPES" > /dev/null; then
    echo "::error file=$TYPES::stale; this is not what the schema describes"
    failures=$((failures + 1))
fi

if [ "$failures" -ne 0 ]; then
    cat >&2 <<'EOF'

Both files have just been rewritten in place, so the fix is to review the diff and commit it.
The regeneration is exactly:

    (cd backend && uv run python -m app.openapi)
    (cd frontend && npm run types)

Generating either of them any other way produces bytes that describe the same API and still fail
this check.
EOF
    exit 1
fi

echo "    ok    the schema and its types are the ones this backend serves"
