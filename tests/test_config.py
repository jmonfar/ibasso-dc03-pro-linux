"""Tests for the on-disk config layer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from dc03.core.config import (
    DeviceNotFoundError,
    DeviceRecord,
    GeneralSettings,
    VolumeSettings,
    config_dir,
    device_path,
    forget_device,
    general_path,
    load_device,
    load_general,
    load_volume,
    resolve_device_path,
    save_device,
    save_general,
    save_volume,
)


# ---- fixtures / helpers ----


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect XDG config and the sysfs root into tmp_path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(
        "dc03.core.device.DEFAULT_SYS_ROOT",
        tmp_path / "sys",
    )
    return tmp_path


def _make_valid_hidraw(root: Path, name: str = "hidraw5") -> Path:
    """Create a fake hidraw node plus its sysfs entry; return the dev path."""
    dev = root / name
    dev.touch()
    uevent_dir = root / "sys" / "class" / "hidraw" / name / "device"
    uevent_dir.mkdir(parents=True)
    (uevent_dir / "uevent").write_text("HID_ID=0003:0000262A:0000187E\n")
    return dev


# ---- config_dir ----


def test_config_dir_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "myxdg"))
    assert config_dir() == tmp_path / "myxdg" / "dc03"


def test_config_dir_falls_back_to_home_dotconfig(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert config_dir() == Path.home() / ".config" / "dc03"


# ---- general.toml ----


def test_load_general_returns_defaults_when_missing(isolated):
    assert load_general() == GeneralSettings()


def test_general_round_trips(isolated):
    save_general(GeneralSettings(filter=4, gain=2, output=1, balance=-10))
    assert load_general() == GeneralSettings(
        filter=4, gain=2, output=1, balance=-10
    )


def test_save_general_leaves_no_temp_file(isolated):
    save_general(GeneralSettings(filter=2, gain=1, output=0, balance=5))
    files = sorted(p.name for p in general_path().parent.iterdir())
    assert files == ["general.toml"]


# ---- volume.toml ----


def test_load_volume_returns_defaults_when_missing(isolated):
    assert load_volume() == VolumeSettings()


def test_volume_round_trips_with_timestamp(isolated):
    ts = datetime(2026, 5, 15, 9, 14, 1, tzinfo=timezone.utc)
    save_volume(VolumeSettings(volume=42, updated_at=ts))
    loaded = load_volume()
    assert loaded.volume == 42
    assert loaded.updated_at == ts


def test_volume_round_trips_without_timestamp(isolated):
    save_volume(VolumeSettings(volume=88))
    assert load_volume() == VolumeSettings(volume=88, updated_at=None)


# ---- device.toml ----


def test_load_device_returns_none_when_missing(isolated):
    assert load_device() is None


def test_device_round_trips(isolated):
    ts = datetime(2026, 5, 15, 9, 12, 33, tzinfo=timezone.utc)
    save_device(DeviceRecord(path="/dev/hidraw5", attached_at=ts))
    loaded = load_device()
    assert loaded is not None
    assert loaded.path == "/dev/hidraw5"
    assert loaded.attached_at == ts


def test_forget_device_removes_file(isolated):
    save_device(DeviceRecord(path="/dev/hidraw5"))
    assert device_path().exists()
    forget_device()
    assert not device_path().exists()


def test_forget_device_is_idempotent_when_missing(isolated):
    forget_device()
    forget_device()  # second call must not raise


# ---- resolve_device_path ----


def test_resolve_with_explicit_valid_path(isolated):
    dev = _make_valid_hidraw(isolated, "hidraw5")
    assert resolve_device_path(dev) == dev


def test_resolve_with_explicit_invalid_path_raises(isolated):
    bogus = isolated / "nonexistent"
    with pytest.raises(DeviceNotFoundError):
        resolve_device_path(bogus)


def test_resolve_falls_back_to_config_when_valid(isolated):
    dev = _make_valid_hidraw(isolated, "hidraw5")
    save_device(DeviceRecord(path=str(dev)))
    assert resolve_device_path(None) == dev


def test_resolve_raises_when_stored_path_is_stale(isolated):
    save_device(DeviceRecord(path=str(isolated / "gone")))
    with pytest.raises(DeviceNotFoundError):
        resolve_device_path(None)


def test_resolve_raises_when_nothing_known(isolated):
    with pytest.raises(DeviceNotFoundError):
        resolve_device_path(None)
