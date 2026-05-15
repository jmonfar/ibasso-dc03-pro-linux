"""Tests for hidraw I/O — sysfs validation, batch writes, input reads."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dc03.core.device import (
    read_input_report,
    send_batch,
    validate_hidraw_path,
)


# ---- helpers ----


def _make_fake_sysfs(
    tmp_path: Path,
    hidraw_name: str,
    hid_id: str = "HID_ID=0003:0000262A:0000187E",
) -> tuple[Path, Path]:
    """Construct a (dev_node, sys_root) pair under tmp_path."""
    dev_node = tmp_path / hidraw_name
    dev_node.touch()
    uevent_dir = tmp_path / "sys" / "class" / "hidraw" / hidraw_name / "device"
    uevent_dir.mkdir(parents=True)
    (uevent_dir / "uevent").write_text(hid_id + "\n")
    return dev_node, tmp_path / "sys"


# ---- validate_hidraw_path ----


def test_validate_path_matches_dc03(tmp_path: Path):
    dev, sysroot = _make_fake_sysfs(tmp_path, "hidraw5")
    assert validate_hidraw_path(dev, sys_root=sysroot) is True


def test_validate_path_with_other_uevent_keys(tmp_path: Path):
    """Real uevent files have multiple keys; HID_ID must still be found."""
    dev, sysroot = _make_fake_sysfs(
        tmp_path,
        "hidraw5",
        hid_id=(
            "DRIVER=hid-generic\n"
            "HID_ID=0003:0000262A:0000187E\n"
            "HID_NAME=DC03 Pro\n"
            "HID_PHYS=usb-0000:00:14.0-1.2/input2"
        ),
    )
    assert validate_hidraw_path(dev, sys_root=sysroot) is True


def test_validate_path_rejects_wrong_vid_pid(tmp_path: Path):
    dev, sysroot = _make_fake_sysfs(
        tmp_path,
        "hidraw5",
        hid_id="HID_ID=0003:0000046D:0000C52B",  # Logitech receiver
    )
    assert validate_hidraw_path(dev, sys_root=sysroot) is False


def test_validate_path_rejects_missing_node(tmp_path: Path):
    sysroot = tmp_path / "sys"
    sysroot.mkdir()
    nonexistent = tmp_path / "hidraw99"
    assert validate_hidraw_path(nonexistent, sys_root=sysroot) is False


def test_validate_path_rejects_missing_sysfs_entry(tmp_path: Path):
    dev = tmp_path / "hidraw5"
    dev.touch()
    sysroot = tmp_path / "sys"
    sysroot.mkdir()
    # No /sys/class/hidraw/hidraw5/device/uevent
    assert validate_hidraw_path(dev, sys_root=sysroot) is False


def test_validate_path_rejects_malformed_hid_id(tmp_path: Path):
    dev, sysroot = _make_fake_sysfs(
        tmp_path,
        "hidraw5",
        hid_id="HID_ID=not-a-valid-id",
    )
    assert validate_hidraw_path(dev, sys_root=sysroot) is False


# ---- send_batch ----


def test_send_batch_writes_each_report_with_report_id_prefix(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("time.sleep", lambda _: None)
    target = tmp_path / "fake_hidraw"
    target.touch()

    reports = [bytes([0x11] * 16), bytes([0x22] * 16), bytes([0x33] * 16)]
    send_batch(target, reports)

    expected = b"".join(b"\x00" + r for r in reports)
    assert target.read_bytes() == expected


def test_send_batch_sleeps_between_reports_but_not_after_last(
    tmp_path: Path, monkeypatch
):
    target = tmp_path / "fake_hidraw"
    target.touch()
    calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda d: calls.append(d))

    send_batch(target, [bytes(16), bytes(16), bytes(16)], gap=0.005)

    # 3 reports => 2 inter-report gaps
    assert calls == [0.005, 0.005]


def test_send_batch_rejects_wrong_size_report_before_opening(
    tmp_path: Path, monkeypatch
):
    """Validation runs before any I/O — file must remain empty."""
    monkeypatch.setattr("time.sleep", lambda _: None)
    target = tmp_path / "fake_hidraw"
    target.touch()

    with pytest.raises(ValueError):
        send_batch(target, [bytes(16), bytes(15)])

    assert target.read_bytes() == b""


def test_send_batch_raises_on_missing_path(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        send_batch(tmp_path / "nonexistent", [bytes(16)])


# ---- read_input_report ----


def test_read_input_report_returns_one_report(tmp_path: Path):
    src = tmp_path / "fake_input"
    payload = bytes(range(32))
    src.write_bytes(payload + b"trailing data that should not be read")

    fd = os.open(str(src), os.O_RDONLY)
    try:
        result = read_input_report(fd)
    finally:
        os.close(fd)

    assert result == payload
    assert len(result) == 32
