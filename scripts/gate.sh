#!/usr/bin/env bash
#
# Every check CI runs, run here first.
#
# The rule this exists to serve is that nothing is committed before a green gate. That rule was
# already in force and still let a stale generated file reach CI, because the gate was a handful of
# commands typed from memory each time: the ones that were remembered ran, the ones that were not
# were not merely skipped but invisible, and the report afterwards said "lint, types and design are
# green" — which was true, and which described a gate missing a check.
#
# So the gate is a file. Adding a check to CI without adding it here is now a visible omission
# rather than a thing to remember, and the checks that have a script are invoked through that same
# script rather than through a copy of its commands.
#
# THREE EXIT CODES, BECAUSE "COULD NOT JUDGE" IS NOT "PASSED".
#
#   0  every check ran and passed
#   1  a check failed
#   2  a check could not run, so the gate has no opinion
#
# The third is the important one. Some checks need something this machine may not have — a
# database, the API, docker. A gate that quietly skipped those would report success for a run that
# proved less than the last one, which is the exact shape of the failure above. It names what it
# could not run and refuses to call the result green.
#
# Usage:  ./scripts/gate.sh

set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

readonly API='http://127.0.0.1:8000'

passed=()
failed=()
skipped=()

bold() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# Runs one check and records the outcome instead of aborting, so a single failure does not hide
# the state of everything after it. `set -e` is suspended for the call for the same reason.
run() {
    local name="$1"
    shift
    bold "$name"
    set +e
    "$@"
    local status=$?
    set -e
    if [ "$status" -eq 0 ]; then
        passed+=("$name")
    else
        failed+=("$name")
    fi
}

# The same, in a directory. A subshell rather than `env -C`, which is a GNU extension: the units
# check already documents that the bash on a stock macOS is 3.2, and a gate that only runs on a
# machine with newer tools than the project claims to need is a gate somebody stops running.
run_in() {
    local directory="$1"
    local name="$2"
    shift 2
    bold "$name"
    set +e
    ( cd "$directory" && "$@" )
    local status=$?
    set -e
    if [ "$status" -eq 0 ]; then
        passed+=("$name")
    else
        failed+=("$name")
    fi
}

skip() {
    local name="$1"
    local because="$2"
    bold "$name"
    printf '    SKIPPED  %s\n' "$because"
    skipped+=("$name — $because")
}

have() { command -v "$1" > /dev/null 2>&1; }

# ---------------------------------------------------------------------------------------------
# Static checks. Nothing to install, nothing to be running.
# ---------------------------------------------------------------------------------------------

# Every script this gate goes on to run, checked before it runs them. Missing from the first
# version of this file, which is worth stating plainly: the gate written to stop a check living
# only in CI was itself missing a check that lived only in CI.
if have shellcheck; then
    run 'shellcheck' shellcheck --severity=warning --shell=bash deploy/*.sh scripts/*.sh
else
    skip 'shellcheck' 'shellcheck is not installed; brew install shellcheck'
fi

run 'systemd units' ./deploy/check-units.sh
run 'internal numbering' ./scripts/check-numbering.sh

if have docker && docker info > /dev/null 2>&1; then
    run 'Caddyfile' docker run --rm \
        -v "$PWD/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" \
        caddy:2-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
else
    skip 'Caddyfile' 'docker is not running; CI validates it with the Caddy that serves production'
fi

# ---------------------------------------------------------------------------------------------
# Backend. `--frozen` everywhere, matching CI, so the gate cannot quietly resolve a new dependency
# and check a dependency set that exists nowhere else.
# ---------------------------------------------------------------------------------------------

if ! have uv; then
    skip 'backend' 'uv is not on PATH'
else
    run_in backend 'uv lock --check' uv lock --check
    run_in backend 'ruff check' uv run --frozen ruff check .
    run_in backend 'ruff format --check' uv run --frozen ruff format --check .
    run_in backend 'mypy' uv run --frozen mypy

    # pytest is simply run. It resolves its own database and refuses loudly with the URL when
    # nothing answers, which is better than anything a probe here could say — and a probe would be
    # a second opinion about where the database is, able to disagree with the suite's own.
    run_in backend 'pytest' uv run --frozen pytest -q
fi

# ---------------------------------------------------------------------------------------------
# Frontend.
# ---------------------------------------------------------------------------------------------

if ! have npm; then
    skip 'frontend' 'npm is not on PATH'
else
    run_in frontend 'eslint' npm run lint --silent
    run_in frontend 'prettier --check' npm run format:check --silent
    run_in frontend 'vue-tsc' npm run typecheck --silent
    run_in frontend 'vitest' npm run test --silent

    # After the type check rather than before: a stale schema is most often noticed as a type
    # error, and the type error names the line while this names the file.
    if have uv; then
        run 'schema and types' ./scripts/check-schema.sh
    else
        skip 'schema and types' 'uv is not on PATH, and the schema is generated by the backend'
    fi

    # The design rules read the built CSS, so the build is part of the check rather than a step
    # somebody is expected to have run first.
    run_in frontend 'frontend build' npm run build --silent
    run 'design rules' ./scripts/check-design.sh

    # Playwright drives the built frontend against the real API, which it does not start. A stale
    # server on this port once served a different database and made two tests fail for a reason
    # that had nothing to do with the code, so this reports what answered.
    if health="$(curl -fsS --max-time 3 "$API/api/health" 2>/dev/null)"; then
        printf '\n    the API on %s says: %s\n' "$API" \
            "$(printf '%s' "$health" | tr -d ' \n' | head -c 200)"
        run_in frontend 'playwright' npm run test:e2e --silent
    else
        skip 'playwright' "nothing answered on $API; start the API before the gate can judge the browser tests"
    fi
fi

# ---------------------------------------------------------------------------------------------

bold 'the gate'

# Guarded rather than expanded directly: `"${empty[@]}"` under `set -u` is an error on bash 3.2,
# and a summary that crashed on a run with nothing to report would be the worst possible place for
# this script to fail.
list() {
    local label="$1"
    shift
    [ "$#" -gt 0 ] || return 0
    for entry in "$@"; do printf '    %s  %s\n' "$label" "$entry"; done
}

list 'ok      ' ${passed[@]+"${passed[@]}"}
list 'SKIPPED ' ${skipped[@]+"${skipped[@]}"}
list 'FAILED  ' ${failed[@]+"${failed[@]}"}

if [ "${#failed[@]}" -ne 0 ]; then
    printf '\n%s check(s) failed. Nothing should be committed on this.\n' "${#failed[@]}"
    exit 1
fi

if [ "${#skipped[@]}" -ne 0 ]; then
    printf '\n%s check(s) could not run, so this gate is not green — it has no opinion.\n' \
        "${#skipped[@]}"
    exit 2
fi

printf '\nthe gate is green: every check CI runs ran here and passed\n'
