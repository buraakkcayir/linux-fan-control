#!/usr/bin/env bash

SET_ACER_PROFILE() {
    local TARGET_PROFILE="$1"
    local APPLIED=0

    # Standard Acer WMI Platform Profile
    for path in /sys/devices/platform/acer-wmi/platform-profile/platform-profile-*/profile; do
        if [ -w "$path" ]; then
            echo "$TARGET_PROFILE" > "$path" 2>/dev/null
            APPLIED=1
            break
        fi
    done

    # Dedicated Acer thermal node (if present)
    if [ -w "/sys/devices/platform/acer-wmi/nitro_sense/thermal_profile" ]; then
        echo "$TARGET_PROFILE" > "/sys/devices/platform/acer-wmi/nitro_sense/thermal_profile" 2>/dev/null
    fi

    if [ "$APPLIED" -eq 1 ]; then
        echo "[Acer-Auto] -> Applied thermal profile: $TARGET_PROFILE"
    fi
}

RUN_SCX_COMMAND() {
    local MODE="$1"
    shift

    if ! command -v scxctl >/dev/null 2>&1; then
        echo "[SCX-Auto] scxctl is not available; skipping scheduler change." >&2
        return 1
    fi

    case "$MODE" in
        "switch")
            scxctl switch "$@"
            ;;
        "start")
            scxctl start "$@"
            ;;
        "stop")
            scxctl stop
            ;;
        *)
            echo "[SCX-Auto] Unsupported scheduler action: $MODE" >&2
            return 1
            ;;
    esac
}

POWER_PROFILE() {
    if command -v powerprofilesctl >/dev/null 2>&1; then
        powerprofilesctl get 2>/dev/null
    else
        printf '%s\n' "balanced"
    fi
}

SCX_PROFILE_STILL_ACTIVE() {
    local EXPECTED_PROFILE="$1"
    [ "$(POWER_PROFILE)" = "$EXPECTED_PROFILE" ]
}

STOP_STALE_SCX_SCHEDULER() {
    sleep 1
    if ! SCX_PROFILE_STILL_ACTIVE "$1"; then
        RUN_SCX_COMMAND stop
    fi
}

APPLY_HARDWARE_TWEAKS() {
    local MODE="$1"

    # AMD Energy Performance Preference (EPP)
    local EPP_VAL="balance_performance"
    [ "$MODE" = "quiet" ] && EPP_VAL="power"
    [ "$MODE" = "performance" ] && EPP_VAL="performance"

    for epp in /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference; do
        [ -w "$epp" ] && echo "$EPP_VAL" > "$epp" 2>/dev/null
    done

    # PCIe ASPM (Active State Power Management)
    local ASPM_PATH="/sys/module/pcie_aspm/parameters/policy"
    if [ -w "$ASPM_PATH" ]; then
        local ASPM_VAL="default"
        [ "$MODE" = "quiet" ] && ASPM_VAL="powersave"
        [ "$MODE" = "performance" ] && ASPM_VAL="performance"
        echo "$ASPM_VAL" > "$ASPM_PATH" 2>/dev/null
    fi
}

APPLY_PROFILE() {
    PROFILE="$(POWER_PROFILE)"

    echo "[SCX-Auto] Power profile detected: ${PROFILE:-balanced}"

    case "$PROFILE" in
        "performance")
            echo "[SCX-Auto] -> Performance mode: activating scx_bpfland..."
            RUN_SCX_COMMAND switch -s bpfland || RUN_SCX_COMMAND start -s bpfland
            if ! SCX_PROFILE_STILL_ACTIVE "performance"; then
                echo "[SCX-Auto] -> Profile changed during scheduler activation; stopping stale scheduler."
                STOP_STALE_SCX_SCHEDULER "performance"
                return
            fi
            SET_ACER_PROFILE "performance"
            APPLY_HARDWARE_TWEAKS "performance"
            ;;
        "power-saver")
            echo "[SCX-Auto] -> Power-saver mode: activating scx_lavd (powersave)..."
            RUN_SCX_COMMAND switch -s lavd -m powersave || RUN_SCX_COMMAND start -s lavd -m powersave
            if ! SCX_PROFILE_STILL_ACTIVE "power-saver"; then
                echo "[SCX-Auto] -> Profile changed during scheduler activation; stopping stale scheduler."
                STOP_STALE_SCX_SCHEDULER "power-saver"
                return
            fi
            SET_ACER_PROFILE "quiet"
            APPLY_HARDWARE_TWEAKS "quiet"
            ;;
        "balanced"|*)
            echo "[SCX-Auto] -> Balanced mode: reverting to default kernel scheduler..."
            RUN_SCX_COMMAND stop
            SET_ACER_PROFILE "balanced"
            APPLY_HARDWARE_TWEAKS "balanced"
            ;;
    esac
}

# Apply current profile immediately on startup
APPLY_PROFILE

# Monitor D-Bus signals (power profile changes, AC power events, etc.)
stdbuf -oL dbus-monitor --system "type='signal',path='/net/hadess/PowerProfiles'" | while read -r line; do
    if echo "$line" | grep -q "ActiveProfile"; then
        APPLY_PROFILE
    fi
done
