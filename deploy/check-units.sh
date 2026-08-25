#!/usr/bin/env bash
#
# Static checks over the systemd units in deploy/.
#
# `systemd-analyze verify` is deliberately not used as the whole check: it resolves ExecStart= and
# fails when the binary is absent, and ours live under /srv/substate-admin on the server. A check
# that cannot pass on a laptop gets `|| true`-d within a week and is then a lie. Its pure parsers
# — `systemd-analyze calendar` and `timespan` — touch nothing and ARE used, when present.
#
# The rule this file exists to enforce, and the one it got wrong once already: a unit's obligations
# follow from HOW IT IS ACTIVATED, not from its Type=. A unit something else starts (a timer, a
# socket, a path) must not carry [Install]; a unit nothing starts must. Judging by Type= is what
# made an earlier version demand [Install] from a timer-driven oneshot — the section whose presence
# would have run the reaper once at every boot, outside its schedule.
#
# Run it exactly as CI does:  ./deploy/check-units.sh

set -Eeuo pipefail

# `mapfile` and associative arrays are bash 4. macOS still ships 3.2, where this would fail with
# "mapfile: command not found" and then quietly check nothing — the failure mode this whole file
# exists to avoid. Say so instead.
if [ "${BASH_VERSINFO[0]:-0}" -lt 4 ]; then
    echo "check-units.sh needs bash 4 or newer; this is ${BASH_VERSION:-unknown}." >&2
    echo "On macOS: brew install bash (the CI runner already has a current one)." >&2
    exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."

failures=0
fail() {
    # The workflow-command prefix lands this on the file in a pull request's diff; elsewhere it is
    # just a readable line.
    echo "::error file=$1::$2"
    failures=$((failures + 1))
}
ok()   { printf '    ok    %s\n' "$1"; }
note() { printf '    note  %s\n' "$1"; }

has_section() {
    grep -qE "^[[:space:]]*\[$2\][[:space:]]*$" "$1"
}

# Every value assigned to KEY inside SECTION, one per line.
#
# Two systemd rules that a naive grep gets wrong, and that cost this project a broken check once:
#   * ExecStart= and WantedBy= are LIST-valued — repeating them appends rather than replaces, and
#     only an empty assignment resets the list. Reading just the last one hides the others.
#   * a line ending in a backslash continues, and a comment line inside that continuation is
#     dropped rather than ending it.
# CRLF is tolerated: a unit edited on Windows would otherwise yield values with a trailing return,
# so `Type=oneshot` would not equal "oneshot" and the unit would be judged as the wrong kind.
directives() {
    awk -v want="$2" -v key="$3" '
        { sub(/\r$/, "") }
        /^[[:space:]]*[#;]/ { next }
        /^[[:space:]]*\[[^]]*\][[:space:]]*$/ {
            s = $0; gsub(/^[[:space:]]*\[|\][[:space:]]*$/, "", s); section = s; next
        }
        section != want { next }
        {
            line = $0
            while (line ~ /\\$/) {
                sub(/\\$/, "", line)
                # Skip comment lines inside the continuation instead of letting one end it:
                # stopping there would silently truncate the value being inspected.
                do {
                    r = getline nxt
                    if (r <= 0) break
                    sub(/\r$/, "", nxt)
                } while (nxt ~ /^[[:space:]]*[#;]/)
                if (r <= 0) break
                sub(/^[[:space:]]+/, "", nxt)
                line = line nxt
            }
            if (match(line, "^[[:space:]]*" key "[[:space:]]*=")) {
                v = substr(line, RLENGTH + 1)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", v)
                if (v == "") { n = 0 } else { values[++n] = v }   # an empty assignment resets
            }
        }
        END { for (i = 1; i <= n; i++) print values[i] }
    ' "$1"
}

# The single effective value of a scalar key (Type=, Unit=, RemainAfterExit=): the last wins.
directive() { directives "$@" | tail -n 1; }

# systemd resolves "foo@nightly.service" to that file if it exists, else to the template
# "foo@.service". Without this a templated unit reads as an orphan and its timer as dangling.
unit_path() {
    local name="$1"
    if [ -f "deploy/$name" ]; then
        printf 'deploy/%s\n' "$name"
        return 0
    fi
    case "$name" in
        *@*.*)
            local template="${name%%@*}@.${name##*.}"
            [ -f "deploy/$template" ] && printf 'deploy/%s\n' "$template" && return 0
            ;;
    esac
    return 1
}

is_true() { case "${1,,}" in 1|yes|on|true) return 0 ;; *) return 1 ;; esac; }

# --- inventory ---------------------------------------------------------------

# A symlinked unit is rejected rather than skipped. `find -type f` would pass over it in silence,
# and silence here means a unit nobody checked.
while IFS= read -r link; do
    fail "$link" "unit file is a symlink; this check reads unit text and does not follow links"
done < <(find deploy -type l \( -name '*.service' -o -name '*.timer' -o -name '*.socket' -o -name '*.path' \) | sort)

mapfile -t services < <(find deploy -type f -name '*.service' | sort)
mapfile -t activators < <(find deploy -type f \( -name '*.timer' -o -name '*.socket' -o -name '*.path' \) | sort)

if [ ${#services[@]} -eq 0 ]; then
    echo "::error::no systemd service unit found under deploy/"
    exit 1
fi

# Which unit each activator starts, and by what. The key= directive differs per activator type, and
# all three default to the service of the same basename when it is absent.
declare -A starts_what=()
for activator in "${activators[@]}"; do
    base="$(basename "$activator")"
    case "$base" in
        *.timer)  target="$(directive "$activator" Timer Unit)" ;;
        *.socket) target="$(directive "$activator" Socket Service)" ;;
        *.path)   target="$(directive "$activator" Path Unit)" ;;
    esac
    starts_what["$activator"]="${target:-${base%.*}.service}"
done

# --- services ----------------------------------------------------------------

echo "services:"
for unit in "${services[@]}"; do
    name="$(basename "$unit")"
    echo "  $name"

    for section in Unit Service; do
        has_section "$unit" "$section" || fail "$unit" "missing [$section] section"
    done

    mapfile -t exec_starts < <(directives "$unit" Service ExecStart)
    if [ ${#exec_starts[@]} -eq 0 ]; then
        fail "$unit" "no ExecStart= in [Service]"
    fi

    type="$(directive "$unit" Service Type)"
    type="${type:-simple}"

    # systemd refuses to load a unit with several ExecStart= unless it is oneshot: "Service has
    # more than one ExecStart= setting, which is only allowed for Type=oneshot services." A stale
    # line left behind by an edit is the realistic way in, and the unit then fails to start at all.
    if [ ${#exec_starts[@]} -gt 1 ] && [ "$type" != oneshot ]; then
        fail "$unit" "Type=$type has ${#exec_starts[@]} ExecStart= lines; systemd allows that only for Type=oneshot"
    fi

    # One uvicorn worker, forever, across EVERY command the unit runs — not just the last
    # ExecStart=. The in-memory world registry and the in-memory login rate limiter are
    # per-process: a sandbox created on one worker is a 404 on another, and N workers mean N times
    # the configured login attempts before anyone is locked out. The count is extracted and
    # compared rather than pattern-matched, because a pattern that knew about 2-9 let `--workers 12`
    # through — and nobody tunes a box up to 4.
    while IFS= read -r command; do
        [ -n "$command" ] || continue
        if printf '%s\n' "$command" | grep -qiE '(^|[[:space:]/])gunicorn([[:space:]]|$)'; then
            fail "$unit" "gunicorn in $command; this project runs exactly one uvicorn worker"
        fi
        workers="$(printf '%s\n' "$command" | sed -nE 's/.*--workers[=[:space:]]+"?([^[:space:]"]+)"?.*/\1/p' | head -n 1)"
        if [ -n "$workers" ] && [ "$workers" != 1 ]; then
            fail "$unit" "--workers $workers; this project runs exactly one uvicorn worker, and that is load-bearing"
        fi
    done < <(for key in ExecStart ExecStartPre ExecStartPost ExecReload; do directives "$unit" Service "$key"; done)

    # Who starts this unit decides everything below.
    started_by=""
    for activator in "${activators[@]}"; do
        [ "${starts_what[$activator]}" = "$name" ] && started_by="$activator"
    done

    if [ -n "$started_by" ]; then
        # Something else activates it, so it must not also be enabled in its own right: [Install]
        # would put it in a boot target and run it once at every boot, outside the schedule.
        if has_section "$unit" Install; then
            fail "$unit" "started by $(basename "$started_by"); it must not carry [Install], or it also runs at every boot"
        else
            ok "started by $(basename "$started_by"), no [Install] — correct"
        fi
        # A oneshot that stays "active" after exiting is never started again by its timer, so the
        # job runs exactly once, ever, and the timer goes quiet without failing.
        if [ "$type" = oneshot ] && is_true "$(directive "$unit" Service RemainAfterExit)"; then
            fail "$unit" "RemainAfterExit on a timer-driven oneshot; it would run once and never again"
        fi
    elif has_section "$unit" Install; then
        mapfile -t wanted < <(for key in WantedBy RequiredBy UpheldBy; do directives "$unit" Install "$key"; done)
        if [ ${#wanted[@]} -eq 0 ]; then
            fail "$unit" "[Install] has no WantedBy=, RequiredBy= or UpheldBy=; systemctl enable would install no symlink"
        else
            for target in "${wanted[@]}"; do
                case "$target" in
                    multi-user.target|default.target|graphical.target) ok "Type=$type, enabled into $target" ;;
                    *) fail "$unit" "[Install] target '$target' is not reached at boot on a server" ;;
                esac
            done
        fi
    else
        fail "$unit" "nothing starts it: no [Install], and no timer, socket or path unit under deploy/ names it"
    fi
done

# --- activators --------------------------------------------------------------

echo "activators:"
for activator in "${activators[@]}"; do
    name="$(basename "$activator")"
    kind="${name##*.}"
    section="$(printf '%s' "${kind^}")"
    echo "  $name"

    for want in Unit "$section" Install; do
        has_section "$activator" "$want" || fail "$activator" "missing [$want] section"
    done

    mapfile -t wanted < <(directives "$activator" Install WantedBy)
    expected="${kind}s.target"
    if [ ${#wanted[@]} -eq 1 ] && [ "${wanted[0]}" = "$expected" ]; then
        ok "[Install] WantedBy=$expected"
    else
        fail "$activator" "[Install] WantedBy must be exactly $expected, found '${wanted[*]:-nothing}'"
    fi

    if [ "$kind" = timer ]; then
        # A timer with no schedule is enabled, active, and never fires.
        schedule=""
        calendars=0
        for key in OnCalendar OnBootSec OnStartupSec OnActiveSec OnUnitActiveSec OnUnitInactiveSec; do
            while IFS= read -r value; do
                [ -n "$value" ] || continue
                schedule="$key=$value"
                [ "$key" = OnCalendar ] && calendars=$((calendars + 1))
                # systemd's own parsers, which read a string and touch nothing else. Without them
                # `OnCalendar=every tuesday` reads as present-and-fine here and is refused by the
                # host, leaving a timer that is enabled, active and dead.
                if command -v systemd-analyze >/dev/null 2>&1; then
                    case "$key" in
                        OnCalendar) systemd-analyze calendar -- "$value" >/dev/null 2>&1 \
                            || fail "$activator" "$key=$value is not valid calendar syntax; systemd would refuse the timer" ;;
                        *) systemd-analyze timespan -- "$value" >/dev/null 2>&1 \
                            || fail "$activator" "$key=$value is not a valid timespan" ;;
                    esac
                fi
            done < <(directives "$activator" Timer "$key")
        done
        if [ -n "$schedule" ]; then
            ok "$schedule"
            command -v systemd-analyze >/dev/null 2>&1 \
                || note "systemd-analyze absent: schedule syntax not validated here, CI does validate it"
        else
            fail "$activator" "no schedule in [Timer]; it would be active and never fire"
        fi

        # Persistent= catches up a missed run, and systemd only tracks that for calendar timers.
        # Next to a monotonic-only schedule it is silently ignored, which reads as a guarantee
        # nobody is giving.
        if is_true "$(directive "$activator" Timer Persistent)" && [ "$calendars" -eq 0 ]; then
            fail "$activator" "Persistent= without OnCalendar=; systemd ignores it for a monotonic timer"
        fi
    fi

    # The failure that hides best: an activator naming a unit that does not exist is enabled,
    # active, and dead. systemd only says so when it elapses.
    target="${starts_what[$activator]}"
    if unit_path "$target" >/dev/null; then
        ok "starts $target"
    else
        fail "$activator" "starts '$target', which is not a unit under deploy/"
    fi
done

echo
if [ "$failures" -gt 0 ]; then
    echo "$failures problem(s) found"
    exit 1
fi
echo "all units pass"
