"""On-disk configuration for the dc03 CLI.

Three TOML files under `~/.config/dc03/` (or `$XDG_CONFIG_HOME/dc03/`),
split by write-frequency and writer identity:

  device.toml   runtime detection state (path + attached_at)
  general.toml  rare-change user prefs (filter, gain, output, balance)
  volume.toml   high-churn user state (volume + updated_at)

All writes are atomic (tempfile in the same directory + fsync + os.replace).
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import protocol
from .device import validate_hidraw_path


class DeviceNotFoundError(Exception):
    """No usable DC03 Pro hidraw path is available via flag or config."""


# ---- Dataclasses ----


@dataclass
class GeneralSettings:
    """Per-control state from `general.toml`.

    Holds the controls the device does NOT persist across power-cycles
    (filter, gain, output mode). `dc03 restore` re-pushes these on every
    attach. Each field is independently optional: `None` means the user
    has never set this control, so restore will skip pushing it and leave
    whatever the device already has.
    """

    filter: int | None = None
    gain: int | None = None
    output: int | None = None


@dataclass
class VolumeSettings:
    """Volume + balance state from `volume.toml`.

    Holds the controls the device DOES persist in NVRAM across
    power-cycles. Replay on attach is a safety-net re-assertion (in case
    the device's state drifted via hardware buttons or another host),
    not load-bearing for the values to survive.

    Balance is grouped with volume because the protocol encodes balance as
    asymmetric L/R attenuation registers in the same multi-report
    transaction as volume — they're one thing at the device level.
    """

    volume: int = 75
    balance: int | None = None
    updated_at: datetime | None = None


@dataclass
class DeviceRecord:
    path: str
    attached_at: datetime | None = None


# ---- Paths ----


def config_dir() -> Path:
    """Return the per-user dc03 config directory (XDG-aware)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "dc03"
    return Path.home() / ".config" / "dc03"


def device_path() -> Path:
    return config_dir() / "device.toml"


def general_path() -> Path:
    return config_dir() / "general.toml"


def volume_path() -> Path:
    return config_dir() / "volume.toml"


# ---- Atomic write primitive ----


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


# ---- general.toml ----


def load_general() -> GeneralSettings | None:
    """Return general settings, or None when no config file exists.

    Keys absent from the file remain `None` on the returned record — the
    caller can then distinguish "user set this" from "user hasn't touched it".
    """
    path = general_path()
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text())
    return GeneralSettings(
        filter=int(data["filter"]) if "filter" in data else None,
        gain=int(data["gain"]) if "gain" in data else None,
        output=int(data["output"]) if "output" in data else None,
    )


def load_general_or_default() -> GeneralSettings:
    """Return general settings, falling back to defaults when absent.

    Use this in interactive subcommands that need a usable record. Use
    plain `load_general()` in code (like `dc03 restore`) that must
    distinguish "user has set something" from "first connection".
    """
    return load_general() or GeneralSettings()


def save_general(settings: GeneralSettings) -> None:
    """Write only the fields that are not None.

    If all fields are None, the file is deleted (if it existed) so a
    subsequent `load_general()` returns None — keeping "user has set
    nothing" semantically distinct from "user has explicitly set values
    that happen to be zero". This is the path the CLI's
    `dc03 <control> --unset` and the GUI's "Keep device default" option
    use to clear settings.

    Saving a record with one field set produces a file containing only
    that key, regardless of what was there before.
    """
    lines: list[str] = []
    if settings.filter is not None:
        lines.append(f"filter = {settings.filter}")
    if settings.gain is not None:
        lines.append(f"gain = {settings.gain}")
    if settings.output is not None:
        lines.append(f"output = {settings.output}")

    path = general_path()
    if not lines:
        path.unlink(missing_ok=True)
        return
    _atomic_write(path, "\n".join(lines) + "\n")


# ---- volume.toml ----


def load_volume() -> VolumeSettings | None:
    """Return volume settings, or None when no config file exists."""
    path = volume_path()
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text())
    updated_at = data.get("updated_at")
    if not isinstance(updated_at, datetime):
        updated_at = None
    balance = int(data["balance"]) if "balance" in data else None
    return VolumeSettings(
        volume=int(data.get("volume", 75)),
        balance=balance,
        updated_at=updated_at,
    )


def load_volume_or_default() -> VolumeSettings:
    """Return volume settings, falling back to defaults when absent."""
    return load_volume() or VolumeSettings()


def save_volume(settings: VolumeSettings) -> None:
    lines = [f"volume = {settings.volume}"]
    if settings.balance is not None:
        lines.append(f"balance = {settings.balance}")
    if settings.updated_at is not None:
        lines.append(f"updated_at = {settings.updated_at.isoformat()}")
    _atomic_write(volume_path(), "\n".join(lines) + "\n")


# ---- device.toml ----


def load_device() -> DeviceRecord | None:
    """Return the current device record, or None if device.toml is absent."""
    path = device_path()
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text())
    raw_path = data.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    attached_at = data.get("attached_at")
    if not isinstance(attached_at, datetime):
        attached_at = None
    return DeviceRecord(path=raw_path, attached_at=attached_at)


def save_device(record: DeviceRecord) -> None:
    lines = [f'path = "{record.path}"']
    if record.attached_at is not None:
        lines.append(f"attached_at = {record.attached_at.isoformat()}")
    _atomic_write(device_path(), "\n".join(lines) + "\n")


def forget_device() -> None:
    """Delete device.toml if it exists; no-op otherwise."""
    try:
        device_path().unlink()
    except FileNotFoundError:
        pass


# ---- Device resolution ----


def resolve_device_path(explicit: str | Path | None) -> Path:
    """Resolve the hidraw path to use.

    Priority: `explicit` flag > `device.toml` > raise `DeviceNotFoundError`.
    Both sources are revalidated against sysfs (`validate_hidraw_path`); a
    stale stored path raises rather than being silently used.
    """
    if explicit is not None:
        path = Path(explicit)
        if not validate_hidraw_path(path):
            raise DeviceNotFoundError(
                f"{path} is not a valid DC03 Pro hidraw node"
            )
        return path

    record = load_device()
    if record is None:
        raise DeviceNotFoundError(
            "DC03 not detected. Plug in the device, or pass --device explicitly."
        )

    path = Path(record.path)
    if not validate_hidraw_path(path):
        raise DeviceNotFoundError(
            f"Stored device path {path} is no longer valid. "
            "Replug the device or pass --device explicitly."
        )
    return path
