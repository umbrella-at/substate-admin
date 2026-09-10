#!/usr/bin/env bash
# deploy/Caddyfile must keep `import /etc/caddy/sites/*.caddy`: without it the other sites on the
# host go dark and `caddy validate` still passes. Run it exactly as CI does: ./deploy/check-caddyfile.sh

set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

readonly CADDYFILE='deploy/Caddyfile'
readonly IMPORT='import /etc/caddy/sites/*.caddy'

# The whole line, uncommented, with this exact absolute path: a relative glob would resolve against
# the checkout when provision.sh validates the file, and against /etc/caddy once it is installed.
if grep -qxF -- "${IMPORT}" "${CADDYFILE}"; then
    printf '    ok    %s: %s\n' "${CADDYFILE}" "${IMPORT}"
    exit 0
fi

echo "::error file=${CADDYFILE}::the line '${IMPORT}' is gone. It is the only thing serving the other sites on this host; without it they stop answering and caddy validate still passes. Put it back as the last line."
exit 1
