#!/bin/sh
# Install the dc03 udev rule and user-level systemd units.
#
# Run as your normal desktop user. sudo will be invoked only for the
# system-level steps (udev rule placement + reload).

set -eu

UDEV_DIR="/etc/udev/rules.d"
USER_SYSTEMD="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [ "$(id -u)" -eq 0 ]; then
    echo "Run as your normal user. sudo will be used where needed." >&2
    exit 1
fi

# Paths are relative to the repo root, where this script is expected to be
# invoked from. Resolve them defensively in case the user runs the script
# from somewhere else.
REPO_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Installing udev rule to $UDEV_DIR (sudo)..."
sudo install -m 0644 udev/70-ibasso-dc03-pro.rules "$UDEV_DIR/"

echo "==> Reloading udev..."
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=hidraw

echo "==> Installing user systemd units to $USER_SYSTEMD..."
install -d "$USER_SYSTEMD"
install -m 0644 systemd/dc03-restore@.service "$USER_SYSTEMD/"
install -m 0644 systemd/dc03-forget@.service  "$USER_SYSTEMD/"
install -m 0644 systemd/dc03-resume.service   "$USER_SYSTEMD/"

echo "==> Reloading user systemd and enabling resume hook..."
systemctl --user daemon-reload
systemctl --user enable dc03-resume.service

cat <<EOF

Done.

  - Plug in (or replug) the DC03 Pro to apply its stored settings.
  - Use the CLI:  dc03 volume 50  /  dc03 filter nos  /  dc03 gain high  ...
  - Status:       systemctl --user list-units 'dc03-*'

Note: \`dc03\` must be on PATH for the systemd units to find it. If you
installed via uv (\`uv sync\`), use \`uv run dc03\` from the repo root, or
expose the venv's bin dir on your PATH.
EOF
