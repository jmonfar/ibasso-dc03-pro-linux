"""Byte-exact tests for the protocol helpers.

Expected outputs derived from the macOS reference implementation
(`DC03ProStatusBar.swift`) by reproducing its frame layout by hand.
"""

from __future__ import annotations

import pytest

from dc03.core.protocol import (
    OUTPUT_REPORT_SIZE,
    VOLUME_STEPS,
    digital_filter_reports,
    gain_reports,
    output_reports,
    volume_from_attenuation,
    volume_reports,
)


# ---- digital_filter_reports ----


def test_filter_fast_rolloff():
    assert digital_filter_reports(0) == [
        bytes.fromhex("11118860000005090000000000000000"),
        bytes.fromhex("12118862000005090000000000000000"),
    ]


def test_filter_nos():
    assert digital_filter_reports(4) == [
        bytes.fromhex("11118860000005090000000400000000"),
        bytes.fromhex("12118862000005090000000400000000"),
    ]


@pytest.mark.parametrize("bad", [-1, 5, 100])
def test_filter_out_of_range_raises(bad: int):
    with pytest.raises(ValueError):
        digital_filter_reports(bad)


# ---- gain_reports ----


def test_gain_low():
    assert gain_reports(0) == [
        bytes.fromhex("15118860000005080000000000000000"),
        bytes.fromhex("16118862000005080000000000000000"),
    ]


def test_gain_medium():
    assert gain_reports(1) == [
        bytes.fromhex("15118860000005080000002000000000"),
        bytes.fromhex("16118862000005080000002000000000"),
    ]


def test_gain_high():
    assert gain_reports(2) == [
        bytes.fromhex("15118860000005080000003100000000"),
        bytes.fromhex("16118862000005080000003100000000"),
    ]


@pytest.mark.parametrize("bad", [-1, 3, 99])
def test_gain_out_of_range_raises(bad: int):
    with pytest.raises(ValueError):
        gain_reports(bad)


# ---- output_reports ----


def test_output_normal():
    assert output_reports(0) == [
        bytes.fromhex("171188600000050b0000001c00000000"),
        bytes.fromhex("181188620000050b0000001c00000000"),
    ]


def test_output_power_saving():
    assert output_reports(1) == [
        bytes.fromhex("171188600000050b0000001e00000000"),
        bytes.fromhex("181188620000050b0000001e00000000"),
    ]


@pytest.mark.parametrize("bad", [-1, 2, 99])
def test_output_out_of_range_raises(bad: int):
    with pytest.raises(ValueError):
        output_reports(bad)


# ---- volume_reports ----


def test_volume_50_balance_zero():
    """volume 50 -> attenuation 0x32; balanced seq set."""
    assert volume_reports(50, 0) == [
        bytes.fromhex("01118860000005090001003200000000"),
        bytes.fromhex("02118860000005090002003200000000"),
        bytes.fromhex("03118862000005090001003200000000"),
        bytes.fromhex("04118862000005090002003200000000"),
        bytes.fromhex("09118860000005070000003200000000"),
        bytes.fromhex("0a118860000005070001003200000000"),
        bytes.fromhex("1311a0a2001001320000000000000000"),
        bytes.fromhex("0b118862000005070000003200000000"),
        bytes.fromhex("0c118862000005070001003200000000"),
        bytes.fromhex("1411a0a2001101320000000000000000"),
    ]


def test_volume_50_balance_positive():
    """balance > 0: right channel less attenuated; right-shifted seq set."""
    assert volume_reports(50, 10) == [
        bytes.fromhex("01118860000005090001003200000000"),
        bytes.fromhex("02118860000005090002003200000000"),
        bytes.fromhex("07118862000005090001002800000000"),
        bytes.fromhex("08118862000005090002002800000000"),
        bytes.fromhex("09118860000005070000003200000000"),
        bytes.fromhex("0a118860000005070001003200000000"),
        bytes.fromhex("1311a0a2001001320000000000000000"),
        bytes.fromhex("0f118862000005070000002800000000"),
        bytes.fromhex("10118862000005070001002800000000"),
        bytes.fromhex("1411a0a2001101280000000000000000"),
    ]


def test_volume_50_balance_negative():
    """balance < 0: left channel less attenuated; left-shifted seq set."""
    assert volume_reports(50, -10) == [
        bytes.fromhex("05118860000005090001002800000000"),
        bytes.fromhex("06118860000005090002002800000000"),
        bytes.fromhex("03118862000005090001003200000000"),
        bytes.fromhex("04118862000005090002003200000000"),
        bytes.fromhex("0d118860000005070000002800000000"),
        bytes.fromhex("0e118860000005070001002800000000"),
        bytes.fromhex("1311a0a2001001280000000000000000"),
        bytes.fromhex("0b118862000005070000003200000000"),
        bytes.fromhex("0c118862000005070001003200000000"),
        bytes.fromhex("1411a0a2001101320000000000000000"),
    ]


def test_volume_100_loudest_has_zero_attenuation():
    reports = volume_reports(100, 0)
    for r in reports:
        # value byte position differs between standard (11) and two-byte (7) frames
        if r[2] == 0x88:
            assert r[11] == 0x00
        else:
            assert r[7] == 0x00


def test_volume_zero_is_silent_both_channels():
    """volume = 0 forces both channel values to 0xFF (silent)."""
    reports = volume_reports(0, 0)
    for r in reports:
        if r[2] == 0x88:
            assert r[11] == 0xFF
        else:
            assert r[7] == 0xFF


def test_volume_zero_with_balance_still_uses_balance_seq_set():
    """When silent, both channels stay 0xFF but balance sign still picks seq set."""
    reports = volume_reports(0, 50)
    assert reports[0][11] == 0xFF
    assert reports[2][11] == 0xFF
    # balance > 0 path: reports[2] uses seq 0x07 (right-shifted), not 0x03 (balanced)
    assert reports[2][0] == 0x07


def test_volume_balance_floors_at_zero():
    """If base - balance underflows, attenuation clamps to 0 (loudest)."""
    # base for volume=80 is 20 (0x14); balance=30 -> right = max(0, 20-30) = 0
    reports = volume_reports(80, 30)
    # reports[2] is the first right-channel PCM write; should have value byte = 0
    assert reports[2][11] == 0x00


@pytest.mark.parametrize("bad_volume", [-1, 101, 1000])
def test_volume_out_of_range_raises(bad_volume: int):
    with pytest.raises(ValueError):
        volume_reports(bad_volume, 0)


@pytest.mark.parametrize("bad_balance", [-256, 256, 1000])
def test_balance_out_of_range_raises(bad_balance: int):
    with pytest.raises(ValueError):
        volume_reports(50, bad_balance)


# ---- general invariants ----


# ---- volume_from_attenuation (reverse lookup) ----


def test_volume_from_attenuation_round_trips_every_index():
    """Every step in VOLUME_STEPS reverse-looks-up to its own index."""
    for i, step in enumerate(VOLUME_STEPS):
        assert volume_from_attenuation(step) == i


def test_volume_from_attenuation_returns_none_for_unknown_value():
    """Attenuation values not in the table return None (no nearest-match)."""
    # 154 is in the 5-unit gap between VOLUME_STEPS[1]=155 and [2]=150
    assert volume_from_attenuation(154) is None
    assert volume_from_attenuation(200) is None
    assert volume_from_attenuation(-1) is None


def test_volume_from_attenuation_boundary_values():
    """Loudest (0) and silent (255) are recoverable."""
    assert volume_from_attenuation(0) == 100   # loudest
    assert volume_from_attenuation(255) == 0   # silent


# ---- general invariants ----


def test_all_reports_are_16_bytes():
    sources = [
        digital_filter_reports(0),
        digital_filter_reports(4),
        gain_reports(0),
        gain_reports(2),
        output_reports(0),
        output_reports(1),
        volume_reports(0, 0),
        volume_reports(50, 0),
        volume_reports(50, 50),
        volume_reports(50, -50),
        volume_reports(100, 0),
    ]
    for reports in sources:
        for r in reports:
            assert len(r) == OUTPUT_REPORT_SIZE == 16
