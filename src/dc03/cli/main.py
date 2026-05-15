"""Command-line interface for DC03 Pro control."""

from __future__ import annotations

import argparse
import errno
import importlib.resources
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dc03.core import protocol
from dc03.core.config import (
    DeviceNotFoundError,
    DeviceRecord,
    VolumeSettings,
    forget_device,
    load_general,
    load_general_or_default,
    load_volume,
    load_volume_or_default,
    resolve_device_path,
    save_device,
    save_general,
    save_volume,
)
from dc03.core.device import send_batch


class CliUsageError(Exception):
    """User-facing error: command can't proceed given the current state."""


# ---- Named-value tables for friendly CLI args ----

_FILTER_NAMES = {
    "fast": protocol.FILTER_FAST_ROLLOFF,
    "fast-rolloff": protocol.FILTER_FAST_ROLLOFF,
    "slow": protocol.FILTER_SLOW_ROLLOFF,
    "slow-rolloff": protocol.FILTER_SLOW_ROLLOFF,
    "short-fast": protocol.FILTER_SHORT_DELAY_FAST,
    "short-delay-fast": protocol.FILTER_SHORT_DELAY_FAST,
    "short-slow": protocol.FILTER_SHORT_DELAY_SLOW,
    "short-delay-slow": protocol.FILTER_SHORT_DELAY_SLOW,
    "nos": protocol.FILTER_NOS,
}

_GAIN_NAMES = {
    "low": protocol.GAIN_LOW,
    "medium": protocol.GAIN_MEDIUM,
    "med": protocol.GAIN_MEDIUM,
    "high": protocol.GAIN_HIGH,
}

_OUTPUT_NAMES = {
    "normal": protocol.OUTPUT_NORMAL,
    "power-saving": protocol.OUTPUT_POWER_SAVING,
    "power": protocol.OUTPUT_POWER_SAVING,
    "ps": protocol.OUTPUT_POWER_SAVING,
}


# ---- argparse type converters ----


def _named_or_int(
    value: str, table: dict[str, int], valid: range, label: str
) -> int:
    """Accept either a name from `table` or a numeric value within `valid`."""
    try:
        n = int(value)
    except ValueError:
        n = None
    if n is not None:
        if n in valid:
            return n
        raise argparse.ArgumentTypeError(
            f"{label} must be {valid.start}..{valid.stop - 1}, got {n}"
        )
    key = value.lower()
    if key in table:
        return table[key]
    names = ", ".join(sorted(set(table)))
    raise argparse.ArgumentTypeError(
        f"{label} must be {valid.start}..{valid.stop - 1} or one of: {names}"
    )


def _filter_arg(s: str) -> int:
    return _named_or_int(s, _FILTER_NAMES, range(5), "filter")


def _gain_arg(s: str) -> int:
    return _named_or_int(s, _GAIN_NAMES, range(3), "gain")


def _output_arg(s: str) -> int:
    return _named_or_int(s, _OUTPUT_NAMES, range(2), "output")


def _volume_arg(s: str) -> int:
    try:
        n = int(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"volume must be an integer, got {s!r}"
        ) from exc
    if not (protocol.MIN_VOLUME <= n <= protocol.MAX_VOLUME):
        raise argparse.ArgumentTypeError(
            f"volume must be {protocol.MIN_VOLUME}..{protocol.MAX_VOLUME}, got {n}"
        )
    return n


def _balance_arg(s: str) -> int:
    try:
        n = int(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"balance must be an integer, got {s!r}"
        ) from exc
    if not (-50 <= n <= 50):
        raise argparse.ArgumentTypeError(f"balance must be -50..50, got {n}")
    return n


# ---- Subcommand implementations ----


def _cmd_volume(args: argparse.Namespace, device: Path) -> None:
    existing = load_volume()
    stored_balance = existing.balance if existing is not None else None
    balance_for_send = stored_balance if stored_balance is not None else 0
    reports = protocol.volume_reports(args.level, balance=balance_for_send)
    send_batch(device, reports)
    save_volume(
        VolumeSettings(
            volume=args.level,
            balance=stored_balance,
            updated_at=datetime.now(timezone.utc),
        )
    )
    print(f"Volume {args.level} applied")


def _cmd_filter(args: argparse.Namespace, device: Path) -> None:
    reports = protocol.digital_filter_reports(args.value)
    send_batch(device, reports)
    general = load_general_or_default()
    general.filter = args.value
    save_general(general)
    print(f"Filter {args.value} applied")


def _cmd_gain(args: argparse.Namespace, device: Path) -> None:
    reports = protocol.gain_reports(args.value)
    send_batch(device, reports)
    general = load_general_or_default()
    general.gain = args.value
    save_general(general)
    print(f"Gain {args.value} applied")


def _cmd_output(args: argparse.Namespace, device: Path) -> None:
    reports = protocol.output_reports(args.value)
    send_batch(device, reports)
    general = load_general_or_default()
    general.output = args.value
    save_general(general)
    print(f"Output {args.value} applied")


def _cmd_balance(args: argparse.Namespace, device: Path) -> None:
    # Changing balance requires re-sending the full volume transaction, which
    # forces us to pick *some* volume value. Without a stored volume we'd be
    # silently writing our default to NVRAM — bail out instead.
    vol = load_volume()
    if vol is None:
        raise CliUsageError(
            "cannot adjust balance without a stored volume. "
            "Set volume first with `dc03 volume <0..100>`."
        )
    reports = protocol.volume_reports(vol.volume, balance=args.value)
    send_batch(device, reports)
    save_volume(
        VolumeSettings(
            volume=vol.volume,
            balance=args.value,
            updated_at=datetime.now(timezone.utc),
        )
    )
    print(f"Balance {args.value} applied")


def _cmd_restore(args: argparse.Namespace, device: Path) -> None:
    # When invoked by udev with --device, refresh device.toml with the path
    # and a timestamp. When invoked without (e.g. dc03-resume.service or by
    # the user manually), device.toml is already current — leave it alone.
    if args.device is not None:
        save_device(
            DeviceRecord(
                path=str(device),
                attached_at=datetime.now(timezone.utc),
            )
        )

    # Push only the settings the user has actually configured. Each control
    # is checked independently — setting just filter and replugging replays
    # filter only, leaving whatever the device has for gain/output/volume.
    general = load_general()
    vol = load_volume()
    reports: list[bytes] = []
    if general is not None:
        if general.filter is not None:
            reports += protocol.digital_filter_reports(general.filter)
        if general.gain is not None:
            reports += protocol.gain_reports(general.gain)
        if general.output is not None:
            reports += protocol.output_reports(general.output)
    if vol is not None:
        balance = vol.balance if vol.balance is not None else 0
        reports += protocol.volume_reports(vol.volume, balance=balance)

    send_batch(device, reports)

    if reports:
        print("Settings restored")
    else:
        print("Device path recorded; no stored settings to restore yet")


def _cmd_forget(_args: argparse.Namespace) -> None:
    forget_device()
    print("Device path cleared")


# ---- System installer (udev rule + systemd user units) ----
#
# Replaces the historical scripts/install.sh and scripts/uninstall.sh:
# bundled data files are read from importlib.resources, so the same code
# path works for editable installs (uv sync), wheel installs, and the
# `uv tool install --from git+URL` flow.
#
# Two user-level systemd units get installed, both fired by the udev attach
# rule: dc03-restore@.service (one-shot settings replay) and
# dc03-watch@.service (long-running button-event watcher). There used to
# be a third (dc03-resume.service) for hibernate-resume, but empirically
# the user-manager's sleep-target integration never fired it on tested
# hardware — see docs/design.md "Resume from suspend / hibernate" before
# re-attempting.


_UDEV_DEST = Path("/etc/udev/rules.d/70-ibasso-dc03-pro.rules")
_UDEV_FILENAME = "70-ibasso-dc03-pro.rules"
_USER_UNITS = ("dc03-restore@.service", "dc03-watch@.service")
_LEGACY_USER_UNITS = ("dc03-forget@.service", "dc03-resume.service")


def _user_systemd_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "systemd" / "user"
    return Path.home() / ".config" / "systemd" / "user"


def _cmd_install_system(_args: argparse.Namespace) -> None:
    if os.geteuid() == 0:
        raise CliUsageError(
            "run as your normal user; sudo will be invoked only for the "
            "system-level udev step."
        )

    data_pkg = importlib.resources.files("dc03._data")
    user_systemd = _user_systemd_dir()

    print(f"==> Installing udev rule to {_UDEV_DEST} (sudo)...")
    with importlib.resources.as_file(
        data_pkg / "udev" / _UDEV_FILENAME
    ) as src:
        subprocess.run(
            ["sudo", "install", "-m", "0644", str(src), str(_UDEV_DEST)],
            check=True,
        )

    print("==> Reloading udev...")
    subprocess.run(["sudo", "udevadm", "control", "--reload"], check=True)
    subprocess.run(
        ["sudo", "udevadm", "trigger", "--subsystem-match=hidraw"], check=True
    )

    print(f"==> Installing user systemd units to {user_systemd}...")
    user_systemd.mkdir(parents=True, exist_ok=True)
    for unit_name in _USER_UNITS:
        with importlib.resources.as_file(
            data_pkg / "systemd" / unit_name
        ) as src:
            dest = user_systemd / unit_name
            shutil.copy(src, dest)
            dest.chmod(0o644)

    print("==> Reloading user systemd...")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)

    print(
        "\nDone. Plug in (or replug) the DC03 Pro to apply its stored "
        "settings.\nRun `dc03 --help` for the available commands."
    )


def _cmd_uninstall_system(_args: argparse.Namespace) -> None:
    if os.geteuid() == 0:
        raise CliUsageError(
            "run as your normal user; sudo will be invoked only for the "
            "system-level udev step."
        )

    user_systemd = _user_systemd_dir()

    # Best-effort disable of legacy units from older installs.
    print("==> Disabling legacy units if present...")
    for legacy in _LEGACY_USER_UNITS:
        subprocess.run(
            ["systemctl", "--user", "disable", legacy],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            check=False,
        )

    print(f"==> Removing user systemd units from {user_systemd}...")
    for name in _USER_UNITS + _LEGACY_USER_UNITS:
        unit_path = user_systemd / name
        if unit_path.exists():
            unit_path.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)

    print(f"==> Removing udev rule from {_UDEV_DEST} (sudo)...")
    subprocess.run(["sudo", "rm", "-f", str(_UDEV_DEST)], check=True)
    subprocess.run(["sudo", "udevadm", "control", "--reload"], check=True)
    subprocess.run(
        ["sudo", "udevadm", "trigger", "--subsystem-match=hidraw"], check=True
    )

    print(
        "\nUninstalled. Stored settings remain at "
        "$XDG_CONFIG_HOME/dc03/ "
        "(or ~/.config/dc03/);\nremove by hand if you want to wipe them."
    )


def _cmd_watch(_args: argparse.Namespace, device: Path) -> None:
    """Long-running watcher: sync hardware-button events into volume.toml.

    Each `fe 01` input report carries the current L attenuation register in
    byte 8 and the current R attenuation register in byte 9. Buttons step
    both registers in lock-step, so:

        base   = max(L, R)                  # quieter channel's attenuation
        volume = volume_from_attenuation(base)
        balance = L - R                     # signed; matches the protocol's
                                            # asymmetric L/R encoding

    Echo reports (marker `00 00`) are filtered out — they only carry a
    stale cache of byte 8 from the previous `fe 01` event.

    Exits cleanly when the device is disconnected (`EIO` / `ENODEV` on
    read), or at EOF when reading from a regular file (used by tests).
    """
    print(f"Watching {device} for button events...", flush=True)
    fd = os.open(str(device), os.O_RDONLY)
    try:
        while True:
            try:
                report = os.read(fd, protocol.INPUT_REPORT_SIZE)
            except OSError as e:
                if e.errno in (errno.EIO, errno.ENODEV):
                    print("Device disconnected; exiting cleanly", flush=True)
                    return
                raise
            if not report:
                return  # EOF (test path)
            if len(report) < protocol.INPUT_REPORT_SIZE:
                continue

            if bytes(report[4:6]) != protocol.MARKER_BUTTON_EVENT:
                continue

            left = report[8]
            right = report[9]
            base = max(left, right)
            volume = protocol.volume_from_attenuation(base)
            if volume is None:
                print(
                    f"dc03 watch: unrecognized attenuation byte 0x{base:02x}; "
                    "skipping",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            balance = left - right
            save_volume(
                VolumeSettings(
                    volume=volume,
                    balance=balance,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            print(
                f"Button event → volume={volume}, balance={balance}",
                flush=True,
            )
    finally:
        os.close(fd)


# ---- Parser & entry point ----


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dc03",
        description="Control the iBasso DC03 Pro USB DAC.",
    )
    parser.add_argument(
        "--device",
        help="hidraw device path; overrides device.toml lookup",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_vol = sub.add_parser("volume", help="set volume (0..100)")
    p_vol.add_argument("level", type=_volume_arg, help="0..100")

    p_filter = sub.add_parser("filter", help="set digital filter")
    p_filter.add_argument(
        "value",
        type=_filter_arg,
        help="0..4 or one of: fast-rolloff, slow-rolloff, "
        "short-delay-fast, short-delay-slow, nos",
    )

    p_gain = sub.add_parser("gain", help="set gain level")
    p_gain.add_argument(
        "value", type=_gain_arg, help="0..2 or one of: low, medium, high"
    )

    p_output = sub.add_parser("output", help="set output mode")
    p_output.add_argument(
        "value",
        type=_output_arg,
        help="0..1 or one of: normal, power-saving",
    )

    p_balance = sub.add_parser("balance", help="set L/R balance (-50..50)")
    p_balance.add_argument("value", type=_balance_arg, help="-50..50")

    sub.add_parser(
        "restore", help="replay stored settings to the device (udev-fired)"
    )
    sub.add_parser(
        "watch",
        help="long-running input-report watcher (udev-fired); "
        "syncs hardware-button volume changes into volume.toml",
    )
    sub.add_parser(
        "forget", help="manually clear the stored device path"
    )
    sub.add_parser(
        "install-system",
        help="install udev rule + systemd user units (sudo for udev)",
    )
    sub.add_parser(
        "uninstall-system",
        help="reverse install-system (leaves stored settings behind)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        no_device_cmds = {
            "forget": _cmd_forget,
            "install-system": _cmd_install_system,
            "uninstall-system": _cmd_uninstall_system,
        }
        if args.command in no_device_cmds:
            no_device_cmds[args.command](args)
            return 0

        device = resolve_device_path(args.device)

        dispatch = {
            "volume": _cmd_volume,
            "filter": _cmd_filter,
            "gain": _cmd_gain,
            "output": _cmd_output,
            "balance": _cmd_balance,
            "restore": _cmd_restore,
            "watch": _cmd_watch,
        }
        dispatch[args.command](args, device)
        return 0
    except (DeviceNotFoundError, CliUsageError) as e:
        print(f"dc03: {e}", file=sys.stderr)
        return 1
    except (FileNotFoundError, PermissionError, OSError) as e:
        print(f"dc03: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
