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
    filter: int = protocol.FILTER_FAST_ROLLOFF
    gain: int = protocol.GAIN_LOW
    output: int = protocol.OUTPUT_NORMAL
    balance: int = 0


@dataclass
class VolumeSettings:
    volume: int = 75
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


def load_general() -> GeneralSettings:
    """Return general settings, or defaults if no config file exists."""
    path = general_path()
    if not path.exists():
        return GeneralSettings()
    data = tomllib.loads(path.read_text())
    return GeneralSettings(
        filter=int(data.get("filter", protocol.FILTER_FAST_ROLLOFF)),
        gain=int(data.get("gain", protocol.GAIN_LOW)),
        output=int(data.get("output", protocol.OUTPUT_NORMAL)),
        balance=int(data.get("balance", 0)),
    )


def save_general(settings: GeneralSettings) -> None:
    content = (
        f"filter = {settings.filter}\n"
        f"gain = {settings.gain}\n"
        f"output = {settings.output}\n"
        f"balance = {settings.balance}\n"
    )
    _atomic_write(general_path(), content)


# ---- volume.toml ----


def load_volume() -> VolumeSettings:
    """Return volume settings, or defaults if no config file exists."""
    path = volume_path()
    if not path.exists():
        return VolumeSettings()
    data = tomllib.loads(path.read_text())
    updated_at = data.get("updated_at")
    if not isinstance(updated_at, datetime):
        updated_at = None
    return VolumeSettings(
        volume=int(data.get("volume", 75)),
        updated_at=updated_at,
    )


def save_volume(settings: VolumeSettings) -> None:
    lines = [f"volume = {settings.volume}"]
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
