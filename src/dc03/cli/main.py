"""Command-line interface for DC03 Pro control."""

from __future__ import annotations

import argparse
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
        "forget", help="manually clear the stored device path"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "forget":
            _cmd_forget(args)
            return 0

        device = resolve_device_path(args.device)

        dispatch = {
            "volume": _cmd_volume,
            "filter": _cmd_filter,
            "gain": _cmd_gain,
            "output": _cmd_output,
            "balance": _cmd_balance,
            "restore": _cmd_restore,
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
