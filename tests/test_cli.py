"""Tests for the dc03 CLI subcommands."""

from __future__ import annotations

from pathlib import Path

import pytest

from dc03.cli.main import main
from dc03.core.config import (
    DeviceRecord,
    GeneralSettings,
    VolumeSettings,
    load_device,
    load_general,
    load_volume,
    save_device,
    save_general,
    save_volume,
)


# ---- fixtures / helpers ----


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect XDG config + sysfs root into tmp_path, and stub send_batch."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr("dc03.core.device.DEFAULT_SYS_ROOT", tmp_path / "sys")

    calls: list[tuple[str, list[bytes]]] = []

    def fake_send_batch(path, reports, gap=0.020):  # noqa: ARG001
        calls.append((str(path), [bytes(r) for r in reports]))

    monkeypatch.setattr("dc03.cli.main.send_batch", fake_send_batch)
    return tmp_path, calls


def _make_valid_hidraw(root: Path, name: str = "hidraw5") -> Path:
    dev = root / name
    dev.touch()
    uevent_dir = root / "sys" / "class" / "hidraw" / name / "device"
    uevent_dir.mkdir(parents=True)
    (uevent_dir / "uevent").write_text("HID_ID=0003:0000262A:0000187E\n")
    return dev


# ---- per-command behaviour ----


def test_volume_sends_10_reports_and_persists(isolated):
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)

    assert main(["--device", str(dev), "volume", "50"]) == 0

    assert len(calls) == 1
    sent_path, reports = calls[0]
    assert sent_path == str(dev)
    assert len(reports) == 10  # volume_reports transaction
    assert load_volume().volume == 50


def test_volume_uses_stored_balance(isolated):
    """Volume command must include the stored balance in the transaction."""
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_volume(VolumeSettings(volume=50, balance=10))

    main(["--device", str(dev), "volume", "50"])

    _, reports = calls[0]
    # balance > 0 selects the right-shifted seq set; reports[2] has seq 0x07
    assert reports[2][0] == 0x07


def test_volume_command_preserves_stored_balance(isolated):
    """Setting volume keeps the existing balance in volume.toml."""
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_volume(VolumeSettings(volume=30, balance=20))

    main(["--device", str(dev), "volume", "60"])

    loaded = load_volume()
    assert loaded.volume == 60
    assert loaded.balance == 20


def test_filter_named_value_resolves(isolated):
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)

    assert main(["--device", str(dev), "filter", "nos"]) == 0

    _, reports = calls[0]
    assert len(reports) == 2
    assert reports[0][11] == 4  # FILTER_NOS as the value byte
    assert load_general().filter == 4


def test_filter_numeric_value_resolves(isolated):
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)

    assert main(["--device", str(dev), "filter", "2"]) == 0

    assert load_general().filter == 2


def test_gain_named_value_resolves(isolated):
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)

    assert main(["--device", str(dev), "gain", "high"]) == 0

    _, reports = calls[0]
    assert reports[0][11] == 0x31  # GAIN_HIGH register value
    assert load_general().gain == 2


def test_output_named_value_resolves(isolated):
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)

    assert main(["--device", str(dev), "output", "power-saving"]) == 0

    _, reports = calls[0]
    assert reports[0][11] == 0x1E  # OUTPUT_POWER_SAVING register value
    assert load_general().output == 1


def test_balance_uses_stored_volume(isolated):
    """Balance command builds a volume transaction using the stored volume."""
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_volume(VolumeSettings(volume=80))

    main(["--device", str(dev), "balance", "10"])

    _, reports = calls[0]
    assert len(reports) == 10
    # VOLUME_STEPS[80] = 20 -> left channel value byte = 0x14
    assert reports[0][11] == 0x14
    loaded = load_volume()
    assert loaded.balance == 10
    assert loaded.volume == 80  # preserved by the balance command


def test_balance_negative_uses_left_shifted_seq_set(isolated):
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_volume(VolumeSettings(volume=50))

    main(["--device", str(dev), "balance", "-10"])

    _, reports = calls[0]
    # balance < 0: reports[0] uses left-shifted seq 0x05
    assert reports[0][0] == 0x05


# ---- restore / forget ----


def test_restore_replays_filter_gain_output_volume(isolated):
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_general(GeneralSettings(filter=4, gain=2, output=1))
    save_volume(VolumeSettings(volume=80))
    save_device(DeviceRecord(path=str(dev)))

    assert main(["restore"]) == 0

    _, reports = calls[0]
    # 2 filter + 2 gain + 2 output + 10 volume = 16
    assert len(reports) == 16


def test_restore_with_volume_balance_uses_balance_seq_set(isolated):
    """volume.toml has balance: restore replays balance inside volume_reports."""
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_device(DeviceRecord(path=str(dev)))
    save_volume(VolumeSettings(volume=50, balance=10))

    assert main(["restore"]) == 0

    _, reports = calls[0]
    assert len(reports) == 10
    # balance > 0: reports[2] uses right-shifted seq 0x07
    assert reports[2][0] == 0x07


def test_restore_with_explicit_device_persists_path(isolated):
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_general(GeneralSettings())
    save_volume(VolumeSettings())

    assert main(["--device", str(dev), "restore"]) == 0

    record = load_device()
    assert record is not None
    assert record.path == str(dev)
    assert record.attached_at is not None


def test_restore_without_device_uses_config(isolated):
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_device(DeviceRecord(path=str(dev)))
    save_general(GeneralSettings())
    save_volume(VolumeSettings())

    assert main(["restore"]) == 0
    assert len(calls) == 1


def test_restore_first_connect_no_config_sends_nothing(isolated, capsys):
    """First connect: record device.toml, send no reports to the DAC."""
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)

    assert main(["--device", str(dev), "restore"]) == 0

    record = load_device()
    assert record is not None
    assert record.path == str(dev)

    # No reports were sent (regardless of whether send_batch was called).
    total = sum(len(reports) for _, reports in calls)
    assert total == 0

    out = capsys.readouterr().out
    assert "no stored settings" in out.lower()


def test_restore_with_only_general_skips_volume(isolated):
    """general.toml exists, volume.toml missing: filter/gain/output only."""
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_device(DeviceRecord(path=str(dev)))
    save_general(GeneralSettings(filter=2, gain=1, output=0))

    assert main(["restore"]) == 0

    _, reports = calls[0]
    # 2 filter + 2 gain + 2 output = 6
    assert len(reports) == 6


def test_restore_with_only_volume_skips_general(isolated):
    """volume.toml exists, general.toml missing: volume reports only."""
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_device(DeviceRecord(path=str(dev)))
    save_volume(VolumeSettings(volume=60))

    assert main(["restore"]) == 0

    _, reports = calls[0]
    # 10 volume reports
    assert len(reports) == 10
    # No general means balance=0 (balanced seq set)
    assert reports[2][0] == 0x03


def test_restore_with_only_one_general_field_set(isolated):
    """User set just filter: restore pushes filter reports only."""
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_device(DeviceRecord(path=str(dev)))
    save_general(GeneralSettings(filter=2))  # gain/output/balance all None

    assert main(["restore"]) == 0

    _, reports = calls[0]
    assert len(reports) == 2  # filter only


def test_filter_then_restore_replays_only_filter(isolated):
    """End-to-end: set filter; replug restore pushes filter only."""
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)

    assert main(["--device", str(dev), "filter", "nos"]) == 0
    calls.clear()

    assert main(["--device", str(dev), "restore"]) == 0
    _, reports = calls[0]
    assert len(reports) == 2  # filter only — not gain/output/volume


def test_balance_without_stored_volume_errors(isolated, capsys):
    """Adjusting balance with no volume set: bail out, don't write to device."""
    tmp_path, calls = isolated
    dev = _make_valid_hidraw(tmp_path)

    assert main(["--device", str(dev), "balance", "10"]) == 1
    err = capsys.readouterr().err
    assert "stored volume" in err
    # No reports sent.
    assert calls == []


def test_forget_clears_device_toml(isolated):
    _, _ = isolated
    save_device(DeviceRecord(path="/dev/hidraw5"))

    assert main(["forget"]) == 0
    assert load_device() is None


def test_forget_idempotent_when_no_device_stored(isolated):
    # Should succeed even with no device.toml; doesn't need a real device.
    assert main(["forget"]) == 0


# ---- error paths ----


def test_no_device_known_returns_nonzero(isolated, capsys):
    assert main(["volume", "50"]) == 1
    err = capsys.readouterr().err
    assert "DC03 not detected" in err


def test_stale_device_path_returns_nonzero(isolated, capsys):
    tmp_path, _ = isolated
    save_device(DeviceRecord(path=str(tmp_path / "gone")))

    assert main(["volume", "50"]) == 1
    err = capsys.readouterr().err
    assert "no longer valid" in err


def test_explicit_invalid_device_returns_nonzero(isolated, capsys):
    tmp_path, _ = isolated
    bogus = tmp_path / "nope"

    assert main(["--device", str(bogus), "volume", "50"]) == 1


def test_invalid_filter_name_argparse_exits(isolated):
    tmp_path, _ = isolated
    dev = _make_valid_hidraw(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["--device", str(dev), "filter", "bogus-filter"])
    assert exc.value.code == 2


def test_invalid_volume_argparse_exits(isolated):
    tmp_path, _ = isolated
    dev = _make_valid_hidraw(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["--device", str(dev), "volume", "150"])
    assert exc.value.code == 2


def test_balance_out_of_ui_range_argparse_exits(isolated):
    tmp_path, _ = isolated
    dev = _make_valid_hidraw(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["--device", str(dev), "balance", "100"])
    assert exc.value.code == 2


# ---- watch ----


def _fe01_report(left: int, right: int) -> bytes:
    """Build a 32-byte `fe 01` input report with given L and R bytes."""
    r = bytearray(32)
    r[4:6] = b"\xfe\x01"
    r[8] = left
    r[9] = right
    return bytes(r)


def _echo_report(seq: int, left_cache: int = 0, right_cache: int = 0) -> bytes:
    """Build a 32-byte `00 00` echo report with given seq + stale-cache bytes."""
    r = bytearray(32)
    # marker bytes 4:6 already 00 00
    r[6] = seq & 0xFF
    r[7] = (seq >> 8) & 0xFF
    r[8] = left_cache
    r[9] = right_cache
    return bytes(r)


def test_watch_records_button_event(isolated):
    """A single fe 01 report updates volume + balance in volume.toml."""
    tmp_path, _ = isolated
    dev = _make_valid_hidraw(tmp_path)
    # L=0x31 (49 → index 51), R=0x1D (29 → balance = 0x14 = 20)
    dev.write_bytes(_fe01_report(0x31, 0x1D))

    assert main(["--device", str(dev), "watch"]) == 0

    loaded = load_volume()
    assert loaded.volume == 51
    assert loaded.balance == 20


def test_watch_ignores_echo_reports(isolated):
    """Echo reports (marker 00 00) don't modify volume.toml."""
    tmp_path, _ = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_volume(VolumeSettings(volume=75, balance=10))
    dev.write_bytes(_echo_report(seq=0x01, left_cache=0xFF, right_cache=0xFF))

    assert main(["--device", str(dev), "watch"]) == 0

    loaded = load_volume()
    assert loaded.volume == 75
    assert loaded.balance == 10


def test_watch_processes_multiple_events_progressively(isolated):
    """Multiple fe 01 reports leave volume.toml at the last event's state."""
    tmp_path, _ = isolated
    dev = _make_valid_hidraw(tmp_path)
    dev.write_bytes(
        _fe01_report(0x32, 0x1E)   # volume 50, balance 20
        + _fe01_report(0x31, 0x1D)  # volume 51, balance preserved
        + _fe01_report(0x30, 0x1C)  # volume 52, balance preserved
    )

    main(["--device", str(dev), "watch"])

    loaded = load_volume()
    assert loaded.volume == 52
    assert loaded.balance == 20


def test_watch_writes_balance_zero_when_channels_equal(isolated):
    """L == R produces balance = 0 in the saved config."""
    tmp_path, _ = isolated
    dev = _make_valid_hidraw(tmp_path)
    dev.write_bytes(_fe01_report(0x32, 0x32))  # volume 50, balance 0

    main(["--device", str(dev), "watch"])

    loaded = load_volume()
    assert loaded.volume == 50
    assert loaded.balance == 0


def test_watch_skips_unrecognized_attenuation(isolated, capsys):
    """An attenuation value not in VOLUME_STEPS logs a warning and skips."""
    tmp_path, _ = isolated
    dev = _make_valid_hidraw(tmp_path)
    save_volume(VolumeSettings(volume=75, balance=0))
    # 0xFC is in a 5-unit gap region; not in VOLUME_STEPS
    dev.write_bytes(_fe01_report(0xFC, 0xFC))

    assert main(["--device", str(dev), "watch"]) == 0

    err = capsys.readouterr().err
    assert "0xfc" in err.lower()
    loaded = load_volume()
    assert loaded.volume == 75  # unchanged
    assert loaded.balance == 0


def test_watch_mixed_stream_only_acts_on_fe01(isolated):
    """A stream of echo + fe01 + echo only updates from the fe01."""
    tmp_path, _ = isolated
    dev = _make_valid_hidraw(tmp_path)
    dev.write_bytes(
        _echo_report(seq=0x01)
        + _fe01_report(0x32, 0x32)   # volume 50, balance 0
        + _echo_report(seq=0x02)
        + _fe01_report(0x31, 0x31)   # volume 51, balance 0
        + _echo_report(seq=0x14)
    )

    main(["--device", str(dev), "watch"])

    loaded = load_volume()
    assert loaded.volume == 51
    assert loaded.balance == 0
