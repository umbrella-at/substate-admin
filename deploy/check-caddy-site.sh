#!/usr/bin/env bash
# deploy/substate-admin.caddy joins the sites of a shared host. This fails on what `caddy validate`
# passes: a second block, a log without the IP mask, a proxy port that is not the API's.

set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

readonly SITE_FILE='deploy/substate-admin.caddy'
readonly UNIT_FILE='deploy/substate-admin-api.service'
readonly SITE_ADDRESS='substate-admin.umbrella-at.uk'

failures=0
fail() {
    echo "::error file=${SITE_FILE}::$1"
    failures=$((failures + 1))
}
ok() { printf '    ok    %s\n' "$1"; }

# The file without comments and blank lines. A `#` starts a comment only at the start of a token,
# and the file has no quoted `#`, so cutting at " #" and at a leading "#" is exact enough here.
code="$(sed -e 's/^[[:space:]]*#.*$//' -e 's/[[:space:]]#.*$//' -e 's/[[:space:]]*$//' "${SITE_FILE}" \
    | grep -v '^$' || true)"

# Top level: lines that are not indented. Exactly the site address opening its block, and the
# closing brace of that block. Anything else at the top level is a second block of some kind.
top="$(printf '%s\n' "${code}" | grep -v '^[[:space:]]' || true)"
expected="$(printf '%s {\n}' "${SITE_ADDRESS}")"
if [[ "${top}" == "${expected}" ]]; then
    ok "one site block, ${SITE_ADDRESS}, and nothing else at the top level"
else
    fail "the top level must be the single block '${SITE_ADDRESS} { ... }'; found:
${top}"
fi

# The log: present, and masked on both fields.
if printf '%s\n' "${code}" | grep -qE '^[[:space:]]+log \{$'; then
    for field in remote_ip client_ip; do
        if printf '%s\n' "${code}" | grep -qE "^[[:space:]]+request>${field} ip_mask \{\$"; then
            ok "log masks request>${field}"
        else
            fail "the access log does not mask request>${field}: a raw client IP would reach the log"
        fi
    done
else
    fail "no access log block in ${SITE_FILE}"
fi

# The port: the proxy target and the unit's --port must be the same number.
site_port="$(printf '%s\n' "${code}" | sed -nE 's/^[[:space:]]+reverse_proxy 127\.0\.0\.1:([0-9]+)$/\1/p')"
unit_port="$(sed -nE 's/.*--host 127\.0\.0\.1 --port ([0-9]+).*/\1/p' "${UNIT_FILE}")"
if [[ -n "${site_port}" && "${site_port}" == "${unit_port}" ]]; then
    ok "reverse_proxy 127.0.0.1:${site_port} matches --port in ${UNIT_FILE}"
else
    fail "reverse_proxy port '${site_port:-none}' does not match the --port '${unit_port:-none}' of ${UNIT_FILE}"
fi

if (( failures > 0 )); then
    exit 1
fi
