#!/bin/sh
# x17blake uninstaller.
# Removes the installed command/package. Backups, presets you saved and
# other state under ~/.config/x17blake/ are USER DATA and are kept.
set -eu

RULE_DST="/etc/udev/rules.d/70-x17blake.rules"

real_home() {
    if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
        getent passwd "$SUDO_USER" | cut -d: -f6
    else
        printf '%s\n' "$HOME"
    fi
}

home=$(real_home)
rm -f "$home/.local/bin/x17blake"
rm -rf "$home/.local/lib/x17blake"
echo "removed : $home/.local/bin/x17blake"
echo "removed : $home/.local/lib/x17blake"

if [ "$(id -u)" = 0 ]; then
    if [ -f "$RULE_DST" ]; then
        rm -f "$RULE_DST"
        command -v udevadm >/dev/null 2>&1 && udevadm control --reload-rules
        echo "removed : $RULE_DST"
    fi
else
    if [ -f "$RULE_DST" ]; then
        echo "rule    : $RULE_DST still present; remove with:"
        echo "          sudo rm $RULE_DST && sudo udevadm control --reload-rules"
    fi
fi

echo "kept    : $home/.config/x17blake/ (backups, presets, macros; delete manually if wanted)"
