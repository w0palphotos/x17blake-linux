#!/bin/sh
# x17blake installer.
#
# Without root: installs the command for the current user
#   - package copy   ~/.local/lib/x17blake/   (x17blake/ package + presets/)
#   - launcher       ~/.local/bin/x17blake
# With sudo (sudo ./install.sh): additionally installs the udev permission
# rule into /etc/udev/rules.d/ (writable even on immutable distros) and
# installs user files into the REAL user's home, never root's.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PKG_SRC="$SCRIPT_DIR/x17blake"
PRESETS_SRC="$SCRIPT_DIR/presets"
RULE_SRC="$SCRIPT_DIR/udev/70-x17blake.rules"
RULE_DST="/etc/udev/rules.d/70-x17blake.rules"

real_home() {
    # $1 = effective user name; resolve the home dir that owns the install
    if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
        getent passwd "$SUDO_USER" | cut -d: -f6
    else
        printf '%s\n' "$HOME"
    fi
}

install_user() {
    home=$1
    libroot="$home/.local/lib/x17blake"
    [ -d "$PKG_SRC" ] || { echo "error: $PKG_SRC not found (run from the repo)"; exit 1; }
    rm -rf "$libroot"
    mkdir -p "$libroot" "$home/.local/bin"
    cp -R "$PKG_SRC" "$libroot/x17blake"
    rm -rf "$libroot/x17blake/__pycache__"
    if [ -d "$PRESETS_SRC" ]; then
        cp -R "$PRESETS_SRC" "$libroot/presets"
    fi
    printf '#!/bin/sh\nPYTHONPATH="%s" exec python3 -m x17blake "$@"\n' "$libroot" \
        > "$home/.local/bin/x17blake"
    chmod 755 "$home/.local/bin/x17blake"
    echo "installed : $libroot"
    echo "launcher  : $home/.local/bin/x17blake"
    case ":$PATH:" in
        *":$home/.local/bin:"*) ;;
        *) echo "note: $home/.local/bin is not in your PATH" ;;
    esac
}

install_rule() {
    if [ -f "$RULE_DST" ] && cmp -s "$RULE_SRC" "$RULE_DST"; then
        echo "udev rule : already installed ($RULE_DST)"
        return 0
    fi
    cp "$RULE_SRC" "$RULE_DST"
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload-rules && udevadm trigger
    fi
    echo "udev rule : installed ($RULE_DST)"
}

if [ "$(id -u)" = 0 ]; then
    install_user "$(real_home)"
    install_rule
    echo "done. try: x17blake info"
else
    install_user "$(real_home)"
    echo
    if [ -f "$RULE_DST" ] || [ -f "/usr/lib/udev/rules.d/70-x17blake.rules" ]; then
        echo "udev rule : already present on this system"
    else
        echo "udev rule : NOT installed yet - device opens will fail with"
        echo "            permission denied until you run one of:"
        echo "  sudo ./install.sh"
        echo "  (or) sudo cp udev/70-x17blake.rules /etc/udev/rules.d/"
        echo "       sudo udevadm control --reload-rules && sudo udevadm trigger"
        echo "  (NixOS: add the rule line to services.udev.extraRules instead)"
    fi
    echo "done. try: x17blake info"
fi
