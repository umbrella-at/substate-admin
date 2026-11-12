#!/usr/bin/env bash

# LONG BECAUSE: this header is the manual the operator reads before running it as root
#
# substate-admin — one-shot provisioning of this project on a SHARED Ubuntu 24.04 host.
#
# The host is not ours. Its owner runs SSH, the firewall, swap, journald and Caddy for every
# project on it, and this script touches none of them: no sshd drop-in, no ufw rule, no swap
# file, no journald cap, no Caddy package or repository, and never /etc/caddy/Caddyfile. It sets
# up what belongs to substate-admin and nothing else:
#
#   * the user substate-admin (locked password, systemd-journal, sudo for its own unit only);
#   * PostgreSQL 18 from PGDG, the role and the database;
#   * uv, /etc/substate-admin/api.env, /srv/substate-admin;
#   * the API unit and the prune timer;
#   * the site file /etc/caddy/sites/substate-admin.caddy, validated together with the whole
#     host config before Caddy is reloaded.
#
# Run ONCE by a human, as root, over SSH. It is idempotent: every step checks
# before it creates, nothing is clobbered, and a second run is a no-op that
# reports what already exists. Re-run it after changing deploy/substate-admin.caddy
# or deploy/substate-admin-api.service to push those files onto the box.
#
# It needs the sibling files from this directory, so get them onto the host first:
#
#     scp -r deploy/ root@host:/opt/substate-admin-src/deploy/
#     DEPLOY_PUBKEY="$(cat ~/.ssh/substate_admin_ci.pub)" \
#         /opt/substate-admin-src/deploy/provision.sh
#
# Environment:
#   DEPLOY_PUBKEY  optional. The CI public key to install for the substate-admin user.
#                  If unset, the script says exactly how to add it later.
#   FORCE=1        optional. Continue on a distribution other than Ubuntu 24.04.
#
# What it deliberately does NOT do:
#   * print the database password, JWT_SECRET or IP_HASH_PEPPER — ever;
#   * rewrite /etc/substate-admin/api.env once it exists (rotating JWT_SECRET
#     logs every user out; rotating IP_HASH_PEPPER invalidates every ip_hash);
#   * start substate-admin-api.service — there is no application code on the
#     host yet, and a crash-looping unit would only spam the journal;
#   * run migrations or touch the database schema. Migration 001 creates the
#     `admin` schema so CI, local and production bootstrap the same way;
#   * restart anything that is not its own. apt runs with NEEDRESTART_MODE=l, so
#     needrestart only lists the services of other projects a library upgrade
#     would want restarted, and leaves them running;
#   * write, rename or delete any file in /etc/caddy other than its own site file.
#
# Caddy:
#   The host's Caddy must already be installed and running, and its Caddyfile must
#   import /etc/caddy/sites/*.caddy; preflight stops the run otherwise. The site file
#   is validated in place, as the caddy user, with every other site of the host: a
#   broken file of another project stops the run too, and in that case ours is put
#   back the way it was (or removed, if it is new) before the script exits, and
#   Caddy is NOT reloaded. Reload, never restart: a restart drops the in-flight
#   requests of every site on the host.
#
# Copyright (c) 2026 Andrei Tarunin. MIT.

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

readonly APP_NAME="substate-admin"
readonly DEPLOY_USER="${APP_NAME}"
readonly DEPLOY_HOME="/home/${DEPLOY_USER}"
readonly DEPLOY_ROOT="/srv/${APP_NAME}"
readonly ENV_DIR="/etc/${APP_NAME}"
readonly ENV_FILE="${ENV_DIR}/api.env"
readonly API_UNIT="${APP_NAME}-api.service"
readonly PRUNE_UNIT="${APP_NAME}-prune.service"
readonly PRUNE_TIMER="${APP_NAME}-prune.timer"
readonly PG_MAJOR="18"
readonly DB_NAME="substate_admin"
readonly DB_ROLE="substate_admin"
readonly PY_VERSION="3.13"
# Pinned so two provisioning runs weeks apart install the same toolchain, and so
# the production Python toolchain version is recorded in the repository rather
# than being "whatever astral.sh served that day".
readonly UV_VERSION="0.12.5"
readonly CADDY_SITES_DIR="/etc/caddy/sites"
readonly CADDY_SITE="${CADDY_SITES_DIR}/${APP_NAME}.caddy"
# The port of the API on 127.0.0.1, registered for this project in /etc/caddy/ports.md on the
# host. deploy/substate-admin-api.service binds it and deploy/substate-admin.caddy proxies to it.
readonly API_PORT="8102"
readonly PLACEHOLDER_RELEASE="${DEPLOY_ROOT}/releases/000-placeholder"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR

# Scratch space for generated files. 0700, wiped on exit — the SQL that carries
# the database password is written here and fed to psql over stdin, never as an
# argument (argv is world-readable through /proc) and never inline in a command
# (the ERR trap below echoes $BASH_COMMAND).
WORK_DIR="$(mktemp -d)"
readonly WORK_DIR

# Set as the script goes, consumed by later steps and the final summary.
PUBKEY_INSTALLED=0
ENV_FILE_CREATED=0
DB_PASSWORD=""
DB_PASSWORD_IS_NEW=0
STEP=0

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

if [[ -t 1 ]]; then
    readonly C_RESET=$'\033[0m' C_BOLD=$'\033[1m' C_DIM=$'\033[2m'
    readonly C_RED=$'\033[31m' C_YELLOW=$'\033[33m' C_GREEN=$'\033[32m'
else
    readonly C_RESET='' C_BOLD='' C_DIM='' C_RED='' C_YELLOW='' C_GREEN=''
fi

step() {
    STEP=$((STEP + 1))
    printf '\n%s==> [%2d] %s%s\n' "${C_BOLD}" "${STEP}" "$*" "${C_RESET}"
}

log()  { printf '     %s\n' "$*"; }
skip() { printf '     %s· %s%s\n' "${C_DIM}" "$*" "${C_RESET}"; }
ok()   { printf '     %s✓ %s%s\n' "${C_GREEN}" "$*" "${C_RESET}"; }
warn() { printf '     %s! %s%s\n' "${C_YELLOW}" "$*" "${C_RESET}" >&2; }

die() {
    printf '\n%sprovision: %s%s\n' "${C_RED}${C_BOLD}" "$*" "${C_RESET}" >&2
    exit 1
}

on_error() {
    local rc=$? line=$1 cmd=$2
    printf '\n%sprovision: FAILED at line %s (exit %s)%s\n' \
        "${C_RED}${C_BOLD}" "${line}" "${rc}" "${C_RESET}" >&2
    printf '%s  command: %s%s\n' "${C_RED}" "${cmd}" "${C_RESET}" >&2
    printf '%s  the host is in a partial state; fix the cause and re-run — this script is idempotent%s\n' \
        "${C_RED}" "${C_RESET}" >&2
}

cleanup() { rm -rf -- "${WORK_DIR}"; }

trap 'on_error "${LINENO}" "${BASH_COMMAND}"' ERR
trap cleanup EXIT

# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

# write_managed_file <path> <mode> <owner:group>  — content on stdin.
# Returns 0 if the file was created or changed, 1 if it was already correct.
# Always used inside `if`, so the ERR trap never sees the "unchanged" 1.
write_managed_file() {
    local dst="$1" mode="$2" owner="$3"
    local tmp="${WORK_DIR}/managed.$$"

    cat >"${tmp}"
    if [[ -f "${dst}" ]] && cmp -s "${tmp}" "${dst}"; then
        rm -f "${tmp}"
        chown "${owner}" "${dst}"
        chmod "${mode}" "${dst}"
        return 1
    fi
    install -D -o "${owner%%:*}" -g "${owner##*:}" -m "${mode}" "${tmp}" "${dst}"
    rm -f "${tmp}"
    return 0
}

# install_repo_file <src> <dst> <mode> <owner:group>
install_repo_file() {
    local src="$1"
    [[ -f "${src}" ]] || die "missing ${src} — run this script from a checkout of the repository"
    write_managed_file "$2" "$3" "$4" <"${src}"
}

apt_install() {
    local missing=() pkg
    for pkg in "$@"; do
        dpkg-query -W -f='${db:Status-Status}\n' "${pkg}" 2>/dev/null | grep -qx installed \
            || missing+=("${pkg}")
    done
    if [[ ${#missing[@]} -eq 0 ]]; then
        skip "already installed: $*"
        return 0
    fi
    log "installing: ${missing[*]}"
    # NEEDRESTART_MODE=l: list, never restart. The services a library upgrade touches are
    # mostly other projects', and restarting them is their owners' call, not this script's.
    DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l \
        apt-get install -y --no-install-recommends "${missing[@]}"
}

# psql as the postgres superuser. `cd /tmp` keeps psql from whining that it
# cannot read root's home; SQL arrives on stdin so passwords never hit argv.
# The port of the PG_MAJOR "main" cluster. On a box that already carries an
# older PGDG cluster, pg_createcluster puts 18/main on 5433 and leaves the old
# one on 5432 — assuming 5432 would create the role in one cluster while the
# application connects to the other. Resolved once, then reused everywhere.
PG_PORT=""
resolve_pg_port() {
    # Not `[[ -n ... ]] && return 0`: as a standalone statement that AND-list
    # returns 1 when the test is false, and `set -e` would abort the script.
    if [[ -n "${PG_PORT}" ]]; then
        return 0
    fi
    PG_PORT="$(pg_lsclusters -h 2>/dev/null \
        | awk -v v="${PG_MAJOR}" '$1 == v && $2 == "main" { print $3 }' | head -n1)"
    [[ -n "${PG_PORT}" ]] \
        || die "no ${PG_MAJOR}/main Postgres cluster found (pg_lsclusters lists none)"
}

# psql as the postgres superuser, always against the cluster we provisioned.
# `cd /tmp` keeps psql from whining that it cannot read root's home; SQL arrives
# on stdin so passwords never hit argv.
psql_postgres() {
    resolve_pg_port
    (cd /tmp && sudo -u postgres psql -X -q -v ON_ERROR_STOP=1 -p "${PG_PORT}" "$@")
}

# ---------------------------------------------------------------------------
# 1. Preflight
# ---------------------------------------------------------------------------

preflight() {
    step "Preflight: root, distribution, repository files, the host's Caddy, the port"

    [[ ${EUID} -eq 0 ]] || die "must run as root"

    local id="" version_id="" pretty=""
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        id="${ID:-}"
        version_id="${VERSION_ID:-}"
        pretty="${PRETTY_NAME:-unknown}"
    fi

    if [[ "${id}" != "ubuntu" || "${version_id}" != "24.04" ]]; then
        if [[ "${FORCE:-0}" == "1" ]]; then
            warn "expected Ubuntu 24.04, found '${pretty}' — continuing because FORCE=1"
        else
            die "expected Ubuntu 24.04, found '${pretty}'; re-run with FORCE=1 to continue anyway"
        fi
    else
        ok "${pretty}"
    fi

    # Fail here rather than half-way through, when the box is already changed.
    local f
    for f in "${APP_NAME}.caddy" "${API_UNIT}" "${PRUNE_UNIT}" "${PRUNE_TIMER}"; do
        [[ -f "${SCRIPT_DIR}/${f}" ]] \
            || die "missing ${SCRIPT_DIR}/${f} — copy the whole deploy/ directory onto the host"
    done
    ok "found deploy/${APP_NAME}.caddy, deploy/${API_UNIT}, deploy/${PRUNE_UNIT} and deploy/${PRUNE_TIMER}"

    # The host's Caddy, not ours: it has to be there already, running, and importing one file per
    # site. Installing or starting it is the host owner's business.
    command -v caddy >/dev/null \
        || die "caddy is not installed; this script never installs it — the host's Caddy belongs to the host"
    id -u caddy >/dev/null 2>&1 || die "there is no caddy user to validate the config as"
    systemctl is-active --quiet caddy \
        || die "caddy.service is not running; this script reloads it and never starts it"
    [[ -d "${CADDY_SITES_DIR}" ]] || die "${CADDY_SITES_DIR} does not exist"
    grep -qxF -- "import ${CADDY_SITES_DIR}/*.caddy" /etc/caddy/Caddyfile \
        || die "/etc/caddy/Caddyfile does not import ${CADDY_SITES_DIR}/*.caddy: a site file there would never be served"
    ok "host Caddy $(caddy version | awk '{print $1}') running, importing ${CADDY_SITES_DIR}/*.caddy"

    # The port is registered for this project, but a registry is only a file. Something else
    # already listening there would turn every API request into somebody else's answer.
    local listener
    listener="$(ss -ltnH "sport = :${API_PORT}" 2>/dev/null || true)"
    if [[ -n "${listener}" ]] && ! systemctl is-active --quiet "${API_UNIT}"; then
        die "port ${API_PORT} is taken, and not by ${API_UNIT}: ${listener}"
    fi
    ok "port ${API_PORT} is free or held by ${API_UNIT}"
}

# ---------------------------------------------------------------------------
# 2. Base packages
# ---------------------------------------------------------------------------

install_base_packages() {
    step "Base packages"

    apt-get update
    # rsync: the deploy uploads releases with it. openssh-client: ssh-keygen checks the CI key.
    apt_install ca-certificates curl rsync openssh-client
    ok "base packages present"
}

# ---------------------------------------------------------------------------
# 3. The substate-admin user
# ---------------------------------------------------------------------------

install_deploy_pubkey() {
    local keys="${DEPLOY_HOME}/.ssh/authorized_keys"

    if [[ -z "${DEPLOY_PUBKEY:-}" ]]; then
        warn "DEPLOY_PUBKEY is not set — the CI key is NOT installed (see the summary)"
        return 0
    fi

    local key
    key="$(printf '%s' "${DEPLOY_PUBKEY}" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    printf '%s\n' "${key}" | ssh-keygen -l -f - >/dev/null 2>&1 \
        || die "DEPLOY_PUBKEY does not parse as an SSH public key"

    if [[ -f "${keys}" ]] && grep -qF -- "${key}" "${keys}"; then
        skip "CI key already present in ${keys}"
    else
        # If the file was populated out of band and does not end in a newline,
        # appending would splice this key onto the tail of the previous one and
        # silently invalidate BOTH. The duplicate check above would then keep
        # matching, so a re-run would not repair it either.
        if [[ -s "${keys}" ]] && [[ -n "$(tail -c1 "${keys}")" ]]; then
            printf '\n' >>"${keys}"
        fi
        printf '%s\n' "${key}" >>"${keys}"
        ok "appended the CI key to ${keys}"
    fi
    chown "${DEPLOY_USER}:${DEPLOY_USER}" "${keys}"
    chmod 600 "${keys}"
    PUBKEY_INSTALLED=1
}

create_deploy_user() {
    step "User: ${DEPLOY_USER}"

    if id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
        skip "user ${DEPLOY_USER} exists"
    else
        # A real login shell: CI ssh's in as this user and runs the deploy.
        useradd --create-home --home-dir "${DEPLOY_HOME}" --shell /bin/bash \
            --comment "${APP_NAME} deploy" "${DEPLOY_USER}"
        ok "created ${DEPLOY_USER}"
    fi
    # No password, ever: key authentication only.
    passwd --lock "${DEPLOY_USER}" >/dev/null

    install -d -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" -m 700 "${DEPLOY_HOME}/.ssh"
    if [[ ! -f "${DEPLOY_HOME}/.ssh/authorized_keys" ]]; then
        install -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" -m 600 /dev/null \
            "${DEPLOY_HOME}/.ssh/authorized_keys"
    fi

    install_deploy_pubkey

    # Read the journal without root, so a failed deploy can print
    # `journalctl -u substate-admin-api -n 50` on its own.
    if id -nG "${DEPLOY_USER}" | tr ' ' '\n' | grep -qx systemd-journal; then
        skip "${DEPLOY_USER} is already in systemd-journal"
    else
        usermod -aG systemd-journal "${DEPLOY_USER}"
        ok "added ${DEPLOY_USER} to systemd-journal"
    fi

    # The narrowest sudo that lets a deploy restart the API and roll back.
    # Nothing else — no shell, no wildcards, no other unit.
    local sudoers="/etc/sudoers.d/${APP_NAME}"
    local sudoers_tmp="${WORK_DIR}/sudoers"
    cat >"${sudoers_tmp}" <<EOF
# ${APP_NAME} — managed by deploy/provision.sh
${DEPLOY_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl start ${API_UNIT}, \\
                                    /usr/bin/systemctl stop ${API_UNIT}, \\
                                    /usr/bin/systemctl restart ${API_UNIT}
EOF
    visudo -cqf "${sudoers_tmp}" || die "generated sudoers file is invalid — refusing to install it"
    if write_managed_file "${sudoers}" 0440 root:root <"${sudoers_tmp}"; then
        ok "wrote ${sudoers} (restart ${API_UNIT} only)"
    else
        skip "${sudoers} already current"
    fi
}

# ---------------------------------------------------------------------------
# 4. PostgreSQL ${PG_MAJOR} from PGDG
# ---------------------------------------------------------------------------

# Resolve the database password into $DB_PASSWORD. Deliberately a setter and
# not a `pw=$(...)` helper: a command substitution runs in a subshell, and a
# freshly generated password would be lost there — the role would end up with
# one secret and api.env with another.
#
# Generated exactly once. On every later run it is read back out of api.env, so
# the role and the service can never drift apart.
resolve_db_password() {
    if [[ -n "${DB_PASSWORD}" ]]; then
        return 0
    fi
    local url=""
    if [[ -f "${ENV_FILE}" ]]; then
        url="$(sed -n 's/^DATABASE_URL=//p' "${ENV_FILE}" | head -n1)"
    fi
    if [[ "${url}" =~ ^[^:]+://[^:@/]+:([^@]+)@ ]]; then
        DB_PASSWORD="${BASH_REMATCH[1]}"
        DB_PASSWORD_IS_NEW=0
    elif [[ -f "${ENV_FILE}" ]]; then
        # api.env exists but no password can be recovered from it. Minting a new
        # one here would ALTER ROLE out from under the running service, while
        # write_env_file would leave api.env untouched — the two would disagree
        # permanently and /api/health would return 503 forever. Stop instead.
        die "${ENV_FILE} exists but its DATABASE_URL is missing or unparsable.
  Refusing to reset the database password out from under a running service.
  Fix DATABASE_URL by hand (or move ${ENV_FILE} aside to start over) and re-run."
    else
        # Hex only: nothing to quote in SQL, nothing to percent-encode in a URL.
        DB_PASSWORD="$(openssl rand -hex 24)"
        DB_PASSWORD_IS_NEW=1
    fi
}

add_pgdg_repo() {
    local keyring="/etc/apt/keyrings/pgdg.asc"
    local list="/etc/apt/sources.list.d/pgdg.list"
    local codename="${VERSION_CODENAME:-noble}"
    local changed=0

    install -d -m 0755 /etc/apt/keyrings
    if [[ -s "${keyring}" ]]; then
        skip "PGDG signing key already at ${keyring}"
    else
        curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o "${WORK_DIR}/pgdg.asc"
        install -m 0644 "${WORK_DIR}/pgdg.asc" "${keyring}"
        ok "installed the PGDG signing key"
        changed=1
    fi

    if write_managed_file "${list}" 0644 root:root <<EOF
# PostgreSQL Global Development Group — managed by deploy/provision.sh
deb [signed-by=${keyring}] https://apt.postgresql.org/pub/repos/apt ${codename}-pgdg main
EOF
    then
        ok "added the PGDG apt repository for ${codename}"
        changed=1
    else
        skip "PGDG apt repository already current"
    fi

    if [[ ${changed} -eq 1 ]]; then
        apt-get update
    fi
}

set_cluster_timezone_utc() {
    local current
    current="$(psql_postgres -tAc 'SHOW timezone')"
    if [[ "${current}" == "UTC" ]]; then
        skip "cluster timezone is already UTC"
        return 0
    fi
    # ALTER SYSTEM keeps postgresql.conf pristine and survives package upgrades.
    psql_postgres <<'SQL'
ALTER SYSTEM SET timezone = 'UTC';
ALTER SYSTEM SET log_timezone = 'UTC';
SQL
    psql_postgres -tAc 'SELECT pg_reload_conf()' >/dev/null
    ok "cluster timezone set to UTC (was ${current})"
}

create_role_and_database() {
    local sql="${WORK_DIR}/role.sql"
    resolve_db_password

    if [[ "$(psql_postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${DB_ROLE}'")" == "1" ]]; then
        if [[ "${DB_PASSWORD_IS_NEW}" == "1" ]]; then
            # Role without api.env: a half-finished run. Nothing can be
            # authenticating with the old password anyway, so realign the two
            # rather than leave the box permanently broken.
            warn "role ${DB_ROLE} exists but ${ENV_FILE} does not; resetting the role password to match"
            printf "ALTER ROLE %s WITH LOGIN PASSWORD '%s';\n" "${DB_ROLE}" "${DB_PASSWORD}" >"${sql}"
            psql_postgres <"${sql}"
        else
            skip "role ${DB_ROLE} exists; password left untouched"
        fi
    else
        printf "CREATE ROLE %s WITH LOGIN PASSWORD '%s';\n" "${DB_ROLE}" "${DB_PASSWORD}" >"${sql}"
        psql_postgres <"${sql}"
        ok "created role ${DB_ROLE}"
    fi
    rm -f "${sql}"

    if [[ "$(psql_postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'")" == "1" ]]; then
        skip "database ${DB_NAME} exists"
        return 0
    fi

    # A deterministic, locale-free collation: sort order must not depend on
    # which glibc the box happens to ship.
    if psql_postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_ROLE} TEMPLATE template0
                         ENCODING 'UTF8' LOCALE_PROVIDER builtin BUILTIN_LOCALE 'C.UTF-8'" \
        >/dev/null 2>"${WORK_DIR}/createdb.err"; then
        ok "created database ${DB_NAME} (builtin locale provider, C.UTF-8)"
    else
        warn "builtin locale provider unavailable: $(tr -d '\n' <"${WORK_DIR}/createdb.err")"
        psql_postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_ROLE} TEMPLATE template0
                          ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'" >/dev/null
        ok "created database ${DB_NAME} (LC_COLLATE=C, LC_CTYPE=C)"
    fi
    # The `admin` schema is intentionally NOT created here — migration 001 owns
    # it, so CI, a laptop and this box all bootstrap through the same code path.
}

setup_postgres() {
    step "PostgreSQL ${PG_MAJOR} from PGDG"

    add_pgdg_repo
    apt_install "postgresql-${PG_MAJOR}"
    systemctl enable --now "postgresql@${PG_MAJOR}-main" >/dev/null 2>&1 \
        || systemctl enable --now postgresql >/dev/null

    set_cluster_timezone_utc
    create_role_and_database
}

# ---------------------------------------------------------------------------
# 5. uv, system-wide
# ---------------------------------------------------------------------------

install_uv() {
    step "uv (provides Python ${PY_VERSION}; the system 3.12 is never used)"

    if [[ -x /usr/local/bin/uv ]]; then
        skip "uv already installed: $(/usr/local/bin/uv --version)"
    else
        # Version-pinned, downloaded, then run — not piped into a shell — so the
        # installer sits on disk and is auditable if this ever needs explaining.
        curl -fsSL "https://astral.sh/uv/${UV_VERSION}/install.sh" -o "${WORK_DIR}/uv-install.sh"
        UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh "${WORK_DIR}/uv-install.sh" >/dev/null
        local installed
        installed="$(/usr/local/bin/uv --version | awk '{print $2}')"
        [[ "${installed}" == "${UV_VERSION}" ]] \
            || die "expected uv ${UV_VERSION}, got ${installed}"
        ok "installed uv ${installed} to /usr/local/bin"
    fi
    command -v uv >/dev/null || die "uv is not on PATH after installation"

    # Pre-fetch the interpreter as ${DEPLOY_USER} so the first deploy is not
    # also the first download. `uv sync` would do this anyway, so a failure
    # here is a warning, not an error.
    if sudo -u "${DEPLOY_USER}" env HOME="${DEPLOY_HOME}" \
        /usr/local/bin/uv python install "${PY_VERSION}" >/dev/null 2>&1; then
        ok "Python ${PY_VERSION} available to ${DEPLOY_USER}"
    else
        warn "could not pre-fetch Python ${PY_VERSION}; the first deploy will download it"
    fi
}

# ---------------------------------------------------------------------------
# 6. /etc/substate-admin/api.env
# ---------------------------------------------------------------------------

write_env_file() {
    step "Secrets: ${ENV_FILE} (root:${DEPLOY_USER}, 0640)"

    install -d -o root -g "${DEPLOY_USER}" -m 0750 "${ENV_DIR}"

    if [[ -f "${ENV_FILE}" ]]; then
        chown "root:${DEPLOY_USER}" "${ENV_FILE}"
        chmod 0640 "${ENV_FILE}"
        skip "${ENV_FILE} exists and was left completely alone"
        log  "rotating JWT_SECRET would log every user out; rotating IP_HASH_PEPPER"
        log  "would invalidate every stored ip_hash — so this file is written once, by hand or by"
        log  "the first run of this script, and never again."
        return 0
    fi

    local jwt pepper tmp
    # Both must be resolved before the heredoc interpolates them.
    resolve_pg_port
    resolve_db_password
    jwt="$(openssl rand -hex 32)"
    pepper="$(openssl rand -hex 32)"
    tmp="${WORK_DIR}/api.env"

    # umask first: the file must never exist, even for an instant, as 0644.
    ( umask 077
      cat >"${tmp}" <<EOF
# ${APP_NAME} — generated by deploy/provision.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Read by ${API_UNIT} (EnvironmentFile) and by ${DEPLOY_USER} when it runs
# alembic. CI never writes this file. Back it up; it cannot be regenerated.
DATABASE_URL=postgresql+psycopg://${DB_ROLE}:${DB_PASSWORD}@127.0.0.1:${PG_PORT}/${DB_NAME}
JWT_SECRET=${jwt}
IP_HASH_PEPPER=${pepper}
APP_ENV=production
EOF
    )
    install -o root -g "${DEPLOY_USER}" -m 0640 "${tmp}" "${ENV_FILE}"
    rm -f "${tmp}"
    ENV_FILE_CREATED=1
    ok "created ${ENV_FILE} with a fresh DATABASE_URL, JWT_SECRET and IP_HASH_PEPPER"
}

# ---------------------------------------------------------------------------
# 7. Directory skeleton and a placeholder web root
# ---------------------------------------------------------------------------

create_skeleton() {
    step "Directories under ${DEPLOY_ROOT}"

    install -d -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" -m 0755 \
        "${DEPLOY_ROOT}" "${DEPLOY_ROOT}/releases" "${DEPLOY_ROOT}/shared"
    ok "${DEPLOY_ROOT}/{releases,shared}"

    # Caddy serves ${DEPLOY_ROOT}/current/web. Until the first deploy swaps the
    # symlink there is no release at all, and Caddy would answer every request
    # with a 500. One throwaway release keeps the site honest in the meantime;
    # the first deploy replaces the symlink and the pruner eventually removes it.
    if [[ -e "${DEPLOY_ROOT}/current" ]]; then
        skip "${DEPLOY_ROOT}/current already points at $(readlink -f "${DEPLOY_ROOT}/current")"
        return 0
    fi

    install -d -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" -m 0755 \
        "${PLACEHOLDER_RELEASE}" "${PLACEHOLDER_RELEASE}/web" "${PLACEHOLDER_RELEASE}/api"
    write_managed_file "${PLACEHOLDER_RELEASE}/web/index.html" 0644 "${DEPLOY_USER}:${DEPLOY_USER}" <<'EOF' || true
<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>substate-admin</title>
<style>
  body { margin: 0; display: grid; place-items: center; min-height: 100vh;
         font: 16px/1.6 ui-sans-serif, system-ui, sans-serif; color: #1f2328; }
  main { text-align: center; padding: 2rem; }
  h1 { margin: 0 0 .5rem; font-size: 1.5rem; letter-spacing: -.01em; }
  p { margin: 0; color: #656d76; }
</style>
<main>
  <h1>substate-admin</h1>
  <p>The host is provisioned. Waiting for the first deploy.</p>
</main>
EOF
    ln -sfn "${PLACEHOLDER_RELEASE}" "${DEPLOY_ROOT}/current"
    chown -h "${DEPLOY_USER}:${DEPLOY_USER}" "${DEPLOY_ROOT}/current"
    ok "placeholder release at ${PLACEHOLDER_RELEASE}, current -> it"
}

# ---------------------------------------------------------------------------
# 8. The Caddy site and the units
# ---------------------------------------------------------------------------

setup_caddy_site() {
    step "Caddy: ${CADDY_SITE}, validate the host config, reload"

    local src="${SCRIPT_DIR}/${APP_NAME}.caddy"
    local previous="${WORK_DIR}/site.previous"
    local had_previous=0

    if [[ -f "${CADDY_SITE}" ]] && cmp -s "${src}" "${CADDY_SITE}"; then
        skip "${CADDY_SITE} already current"
        return 0
    fi
    if [[ -f "${CADDY_SITE}" ]]; then
        cp -p -- "${CADDY_SITE}" "${previous}"
        had_previous=1
    fi

    # Validated in place: the host's Caddyfile is the only file that knows what the other sites
    # are, and it is locked. As the caddy user, because validation opens (and creates) the log
    # file of every site, and a log created by root is one the running Caddy cannot write to —
    # the next reload would then fail for the whole host.
    install -o root -g root -m 0644 "${src}" "${CADDY_SITE}"
    if ! runuser -u caddy -- caddy validate --config /etc/caddy/Caddyfile \
        >"${WORK_DIR}/caddy-validate.log" 2>&1; then
        if (( had_previous )); then
            install -o root -g root -m 0644 "${previous}" "${CADDY_SITE}"
        else
            rm -f -- "${CADDY_SITE}"
        fi
        cat "${WORK_DIR}/caddy-validate.log" >&2
        die "caddy validate rejected the host config with ${CADDY_SITE};
  the file was put back as it was and caddy was NOT reloaded"
    fi
    ok "caddy validate accepted the host config with ${CADDY_SITE}"

    # Reload, never restart: a restart drops the in-flight requests of every site on the host and
    # briefly frees :80, which is exactly when ACME renewal is retried. A failed reload leaves the
    # running config as it was.
    systemctl reload caddy
    ok "reloaded caddy"
}

setup_api_unit() {
    step "systemd unit: ${API_UNIT}"

    if install_repo_file "${SCRIPT_DIR}/${API_UNIT}" "/etc/systemd/system/${API_UNIT}" 0644 root:root; then
        ok "installed /etc/systemd/system/${API_UNIT}"
    else
        skip "/etc/systemd/system/${API_UNIT} already current"
    fi
    systemctl daemon-reload

    # ENABLED but NOT STARTED on purpose. There is no application code on the
    # box until the first deploy, so starting it now would only produce a
    # crash loop in the journal. The first deploy starts it.
    systemctl enable "${API_UNIT}" >/dev/null
    if systemctl is-active --quiet "${API_UNIT}"; then
        ok "${API_UNIT} enabled and already running"
    else
        ok "${API_UNIT} enabled, not started (no application code until the first deploy)"
    fi
}

setup_prune_timer() {
    step "systemd timer: ${PRUNE_TIMER}"

    local changed=0
    if install_repo_file "${SCRIPT_DIR}/${PRUNE_UNIT}" "/etc/systemd/system/${PRUNE_UNIT}" 0644 root:root; then
        changed=1
        ok "installed /etc/systemd/system/${PRUNE_UNIT}"
    else
        skip "/etc/systemd/system/${PRUNE_UNIT} already current"
    fi
    if install_repo_file "${SCRIPT_DIR}/${PRUNE_TIMER}" "/etc/systemd/system/${PRUNE_TIMER}" 0644 root:root; then
        changed=1
        ok "installed /etc/systemd/system/${PRUNE_TIMER}"
    else
        skip "/etc/systemd/system/${PRUNE_TIMER} already current"
    fi
    if (( changed )); then
        systemctl daemon-reload
    fi

    # The TIMER is started now, unlike the API unit. Its service carries the same
    # ConditionPathExists, so before the first deploy the timer simply fires into a quiet skip
    # rather than a failure — and nothing has to remember to switch it on afterwards.
    systemctl enable --now "${PRUNE_TIMER}" >/dev/null
    ok "${PRUNE_TIMER} enabled and running (next: $(systemctl show "${PRUNE_TIMER}" -p NextElapseUSecRealtime --value 2>/dev/null || echo scheduled))"
}

# ---------------------------------------------------------------------------
# 9. Summary
# ---------------------------------------------------------------------------

summary() {
    local host_key="/etc/ssh/ssh_host_ed25519_key.pub"

    printf '\n%s%s\n' "${C_BOLD}" "────────────────────────────────────────────────────────────────"
    printf '%s provisioned%s\n' "${APP_NAME}" "${C_RESET}"
    cat <<EOF

  On this host now:
    user                ${DEPLOY_USER} (locked password, systemd-journal member)
    sudo                ${DEPLOY_USER} may start/stop/restart ${API_UNIT}, nothing else
    postgres            ${PG_MAJOR} from PGDG, cluster timezone UTC
    database            ${DB_NAME} owned by ${DB_ROLE} (schema \`admin\` comes from migration 001)
    uv                  $(/usr/local/bin/uv --version 2>/dev/null || echo 'installed') in /usr/local/bin
    secrets             ${ENV_FILE} (root:${DEPLOY_USER}, 0640)
    releases            ${DEPLOY_ROOT}/{releases,shared,current}
    caddy               ${CADDY_SITE} (host Caddy $(systemctl is-active caddy || true)), log /var/log/caddy/${APP_NAME}.log
    api                 ${API_UNIT} on 127.0.0.1:${API_PORT}, enabled, deliberately not started
    reaper              ${PRUNE_TIMER} enabled and running (daily)

  Left to the host: ssh, the firewall, swap, journald and Caddy itself.

EOF

    if [[ ${ENV_FILE_CREATED} -eq 1 ]]; then
        printf '  %sBack up %s now.%s Its JWT_SECRET and IP_HASH_PEPPER cannot be regenerated:\n' \
            "${C_BOLD}" "${ENV_FILE}" "${C_RESET}"
        printf '  a new JWT_SECRET logs every user out, a new IP_HASH_PEPPER orphans every stored ip_hash.\n\n'
    fi

    printf '  %sStill to do%s\n\n' "${C_BOLD}" "${C_RESET}"

    local n=0
    if [[ ${PUBKEY_INSTALLED} -eq 0 ]]; then
        n=$((n + 1))
        cat <<EOF
  ${n}. Install the CI public key — DEPLOY_PUBKEY was not set, so ${DEPLOY_USER} cannot log in yet.
     On your workstation:

         ssh-keygen -t ed25519 -C '${APP_NAME} ci' -f ~/.ssh/${APP_NAME}-ci -N ''
         ssh root@<server> "cat >> ${DEPLOY_HOME}/.ssh/authorized_keys" < ~/.ssh/${APP_NAME}-ci.pub

     Or simply re-run this script with DEPLOY_PUBKEY="\$(cat ~/.ssh/${APP_NAME}-ci.pub)".

EOF
    fi

    n=$((n + 1))
    cat <<EOF
  ${n}. Put four secrets into the GitHub repository (Settings -> Secrets -> Actions):

         DEPLOY_SSH_KEY      the PRIVATE half of the CI key (~/.ssh/${APP_NAME}-ci)
         DEPLOY_HOST         this server's hostname or IP
         DEPLOY_USER         ${DEPLOY_USER}
         DEPLOY_KNOWN_HOSTS  output of the ssh-keyscan below

     StrictHostKeyChecking stays on, so DEPLOY_KNOWN_HOSTS must be real. From your
     workstation, using the same host string you put in DEPLOY_HOST:

         ssh-keyscan -t ed25519 <server> 2>/dev/null

EOF

    if [[ -r "${host_key}" ]]; then
        cat <<EOF
     Check the result against this host's own fingerprint before trusting it:

         $(ssh-keygen -lf "${host_key}")

EOF
    fi

    n=$((n + 1))
    cat <<EOF
  ${n}. Confirm the DNS A record for ${APP_NAME}.umbrella-at.uk points here with
     Cloudflare proxying OFF — Caddy needs HTTP-01 on port 80 to issue its certificate.

  $((n + 1)). Push to main. The deploy replaces the pre-deploy holding page with the one from
     the repository. ${API_UNIT} stays stopped until application code is deployed — it is
     enabled, but ConditionPathExists keeps it from starting against an empty release directory.

EOF
}

# ---------------------------------------------------------------------------

main() {
    preflight
    install_base_packages
    create_deploy_user
    setup_postgres
    install_uv
    write_env_file
    create_skeleton
    setup_caddy_site
    setup_api_unit
    setup_prune_timer
    summary
}

main "$@"
