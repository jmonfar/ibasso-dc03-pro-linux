#!/bin/sh
# Remove the dc03 udev rule and user-level systemd units.

set -eu

UDEV_DIR="/etc/udev/rules.d"
USER_SYSTEMD="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [ "$(id -u)" -eq 0 ]; then
    echo "Run as your normal user. sudo will be used where needed." >&2
    exit 1
fi

echo "==> Disabling resume hook..."
systemctl --user disable dc03-resume.service 2>/dev/null || true

echo "==> Removing user systemd units..."
rm -f "$USER_SYSTEMD/dc03-restore@.service"
rm -f "$USER_SYSTEMD/dc03-forget@.service"   # legacy: pre-v1 installs may have it
rm -f "$USER_SYSTEMD/dc03-resume.service"
systemctl --user daemon-reload

echo "==> Removing udev rule (sudo)..."
sudo rm -f "$UDEV_DIR/70-ibasso-dc03-pro.rules"
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=hidraw

echo
echo "Uninstalled. Stored settings remain at \$XDG_CONFIG_HOME/dc03/ — remove"
echo "by hand if you also want to wipe them."
