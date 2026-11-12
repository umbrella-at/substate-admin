#!/usr/bin/env bash
# deploy/substate-admin.caddy goes into /etc/caddy/sites/ on a host whose Caddy serves other
# projects too. `caddy validate` (the CI step before this one) catches a file that does not parse;
# this catches the ones that parse and are still wrong:
#
#   * anything but the one site block: a global options block, a :80 or :443 catch-all, a snippet.
#     Inside the host's Caddyfile they either fail the reload of every site or change all of them;
#   * an access log without the IP mask on BOTH remote_ip and client_ip (house rule: no raw client
#     IP in any log);
#   * a proxy port that differs from the one the API unit binds: the site would answer 502 while
#     the API runs, and the deploy smoke check would be the first to notice.
#
# Run it exactly as CI does: ./deploy/check-caddy-site.sh

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
