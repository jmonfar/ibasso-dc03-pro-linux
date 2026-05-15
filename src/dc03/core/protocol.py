"""DC03 Pro USB-HID control protocol.

Constants, frame layouts, and helpers for building 16-byte output reports
and parsing 32-byte input reports. See docs/protocol.md for full details.

Protocol decoded with reference to:
  https://github.com/Chandru03/ibasso-dc03-pro-macos
  MIT License (c) 2026 Chandru03
"""

from __future__ import annotations

# Device identification

VENDOR_ID = 0x262A
PRODUCT_ID = 0x187E

OUTPUT_REPORT_SIZE = 16
INPUT_REPORT_SIZE = 32

# Input report markers (bytes 4:6 of the 32-byte input report)

MARKER_BUTTON_EVENT = b"\xfe\x01"
MARKER_WRITE_ECHO = b"\x00\x00"

# Frame-level constants

_PROTOCOL_TAG = 0x11            # byte 1 of every output report
_CMD_STANDARD = 0x88            # byte 2 for standard register write
_CMD_TWO_BYTE = 0xA0            # byte 2 for two-byte-offset write
_STD_LENGTH = 0x05              # byte 6 for standard register write
_TWO_BYTE_LENGTH = 0x01         # byte 6 for two-byte-offset write

# Device (I2C-like) target addresses

ADDR_DAC_LEFT = 0x60
ADDR_DAC_RIGHT = 0x62
ADDR_AGGREGATE = 0xA2

# Per-control register offsets (filter/gain/output share the standard-write shape)

_OFFSET_FILTER = (0x09, 0x00, 0x00, 0x00)
_OFFSET_GAIN = (0x08, 0x00, 0x00, 0x00)
_OFFSET_OUTPUT = (0x0B, 0x00, 0x00, 0x00)

# Sequence numbers for the rare-change controls

_SEQ_FILTER_LEFT = 0x11
_SEQ_FILTER_RIGHT = 0x12
_SEQ_GAIN_LEFT = 0x15
_SEQ_GAIN_RIGHT = 0x16
_SEQ_OUTPUT_LEFT = 0x17
_SEQ_OUTPUT_RIGHT = 0x18

# Sequence numbers for the two two-byte-offset volume-aggregate writes

_SEQ_VOL_AGG_LEFT = 0x13
_SEQ_VOL_AGG_RIGHT = 0x14

# Filter values (app value is passed through verbatim as the register value)

FILTER_FAST_ROLLOFF = 0
FILTER_SLOW_ROLLOFF = 1
FILTER_SHORT_DELAY_FAST = 2
FILTER_SHORT_DELAY_SLOW = 3
FILTER_NOS = 4
_VALID_FILTERS = frozenset({0, 1, 2, 3, 4})

# Gain values (app -> register byte)

GAIN_LOW = 0
GAIN_MEDIUM = 1
GAIN_HIGH = 2
_GAIN_REGISTER = {
    GAIN_LOW: 0x00,
    GAIN_MEDIUM: 0x20,
    GAIN_HIGH: 0x31,
}

# Output-mode values (app -> register byte)

OUTPUT_NORMAL = 0
OUTPUT_POWER_SAVING = 1
_OUTPUT_REGISTER = {
    OUTPUT_NORMAL: 0x1C,
    OUTPUT_POWER_SAVING: 0x1E,
}

# Volume / balance bounds and the attenuation value meaning "silent"

MIN_VOLUME = 0
MAX_VOLUME = 100
MIN_BALANCE = -255
MAX_BALANCE = 255
_ATTENUATION_SILENT = 0xFF


# 101-element attenuation table copied verbatim from the macOS reference
# project (ibasso-dc03-pro-macos, MIT (c) 2026 Chandru03). Index = user-facing
# volume 0..100; value = DAC attenuation register byte (0 = loudest,
# 255 = silent).

VOLUME_STEPS: tuple[int, ...] = (
    255, 155, 150, 145, 140, 135, 130, 125, 120, 115,
    110, 109, 108, 107, 106, 105, 104, 103, 102, 101,
    100,  99,  98,  97,  96,  95,  94,  93,  92,  91,
     90,  88,  86,  84,  82,  80,  78,  76,  74,  72,
     70,  68,  66,  64,  62,  60,  58,  56,  54,  52,
     50,  49,  48,  47,  46,  45,  44,  43,  42,  41,
     40,  39,  38,  37,  36,  35,  34,  33,  32,  31,
     30,  29,  28,  27,  26,  25,  24,  23,  22,  21,
     20,  19,  18,  17,  16,  15,  14,  13,  12,  11,
     10,   9,   8,   7,   6,   5,   4,   3,   2,   1,
      0,
)


# ---- Low-level frame builders ----


def write_register(
    seq: int,
    device_address: int,
    offset1: int,
    offset2: int,
    offset3: int,
    offset4: int,
    value: int,
) -> bytes:
    """Build the standard 16-byte register-write report."""
    report = bytearray(OUTPUT_REPORT_SIZE)
    report[0] = seq
    report[1] = _PROTOCOL_TAG
    report[2] = _CMD_STANDARD
    report[3] = device_address
    report[6] = _STD_LENGTH
    report[7] = offset1
    report[8] = offset2
    report[9] = offset3
    report[10] = offset4
    report[11] = value
    return bytes(report)


def write_two_byte_offset(
    seq: int,
    device_address: int,
    offset1: int,
    offset2: int,
    value: int,
) -> bytes:
    """Build the 16-byte variant used for the 0xA2 address-space writes."""
    report = bytearray(OUTPUT_REPORT_SIZE)
    report[0] = seq
    report[1] = _PROTOCOL_TAG
    report[2] = _CMD_TWO_BYTE
    report[3] = device_address
    report[4] = offset1
    report[5] = offset2
    report[6] = _TWO_BYTE_LENGTH
    report[7] = value
    return bytes(report)


# ---- High-level helpers ----
#
# Each returns the full ordered list of reports needed to apply the
# corresponding control change. Callers must send them with ~20 ms between
# writes (see docs/protocol.md "multi-report transactions").


def digital_filter_reports(value: int) -> list[bytes]:
    """Two reports (left + right DAC) to set the digital filter.

    value: filter index 0..4 (FILTER_FAST_ROLLOFF .. FILTER_NOS).
    """
    if value not in _VALID_FILTERS:
        raise ValueError(f"filter must be 0..4, got {value}")
    return [
        write_register(_SEQ_FILTER_LEFT, ADDR_DAC_LEFT, *_OFFSET_FILTER, value),
        write_register(_SEQ_FILTER_RIGHT, ADDR_DAC_RIGHT, *_OFFSET_FILTER, value),
    ]


def gain_reports(level: int) -> list[bytes]:
    """Two reports (left + right DAC) to set the gain.

    level: GAIN_LOW (0), GAIN_MEDIUM (1), or GAIN_HIGH (2).
    """
    if level not in _GAIN_REGISTER:
        raise ValueError(f"gain level must be 0, 1, or 2, got {level}")
    register_value = _GAIN_REGISTER[level]
    return [
        write_register(_SEQ_GAIN_LEFT, ADDR_DAC_LEFT, *_OFFSET_GAIN, register_value),
        write_register(_SEQ_GAIN_RIGHT, ADDR_DAC_RIGHT, *_OFFSET_GAIN, register_value),
    ]


def output_reports(mode: int) -> list[bytes]:
    """Two reports (left + right DAC) to set the output mode.

    mode: OUTPUT_NORMAL (0) or OUTPUT_POWER_SAVING (1).
    """
    if mode not in _OUTPUT_REGISTER:
        raise ValueError(f"output mode must be 0 or 1, got {mode}")
    register_value = _OUTPUT_REGISTER[mode]
    return [
        write_register(_SEQ_OUTPUT_LEFT, ADDR_DAC_LEFT, *_OFFSET_OUTPUT, register_value),
        write_register(_SEQ_OUTPUT_RIGHT, ADDR_DAC_RIGHT, *_OFFSET_OUTPUT, register_value),
    ]


def volume_reports(volume: int, balance: int = 0) -> list[bytes]:
    """The 10-report transaction to set volume and balance.

    volume: 0..100 user scale; mapped via VOLUME_STEPS to attenuation.
    balance: -255..255, positive = louder right channel. Default 0.

    When volume = 0 the device is silent on both channels regardless of
    balance, but the balance sign still selects which sequence-number set
    is used (matching the macOS reference behaviour).
    """
    if not (MIN_VOLUME <= volume <= MAX_VOLUME):
        raise ValueError(f"volume must be {MIN_VOLUME}..{MAX_VOLUME}, got {volume}")
    if not (MIN_BALANCE <= balance <= MAX_BALANCE):
        raise ValueError(f"balance must be {MIN_BALANCE}..{MAX_BALANCE}, got {balance}")

    base = VOLUME_STEPS[volume]

    if base == _ATTENUATION_SILENT:
        left = base
        right = base
    elif balance >= 0:
        left = base
        right = max(0, base - balance)
    else:
        left = max(0, base + balance)
        right = base

    if balance == 0:
        left_commands = (0x01, 0x02, 0x09, 0x0A)
        right_commands = (0x03, 0x04, 0x0B, 0x0C)
    elif balance > 0:
        left_commands = (0x01, 0x02, 0x09, 0x0A)
        right_commands = (0x07, 0x08, 0x0F, 0x10)
    else:
        left_commands = (0x05, 0x06, 0x0D, 0x0E)
        right_commands = (0x03, 0x04, 0x0B, 0x0C)

    return _channel_volume_reports(left, right, left_commands, right_commands)


def _channel_volume_reports(
    left: int,
    right: int,
    left_commands: tuple[int, int, int, int],
    right_commands: tuple[int, int, int, int],
) -> list[bytes]:
    l1, l2, ldsd1, ldsd2 = left_commands
    r1, r2, rdsd1, rdsd2 = right_commands
    return [
        write_register(l1, ADDR_DAC_LEFT, 0x09, 0x00, 0x01, 0x00, left),
        write_register(l2, ADDR_DAC_LEFT, 0x09, 0x00, 0x02, 0x00, left),
        write_register(r1, ADDR_DAC_RIGHT, 0x09, 0x00, 0x01, 0x00, right),
        write_register(r2, ADDR_DAC_RIGHT, 0x09, 0x00, 0x02, 0x00, right),
        write_register(ldsd1, ADDR_DAC_LEFT, 0x07, 0x00, 0x00, 0x00, left),
        write_register(ldsd2, ADDR_DAC_LEFT, 0x07, 0x00, 0x01, 0x00, left),
        write_two_byte_offset(_SEQ_VOL_AGG_LEFT, ADDR_AGGREGATE, 0x00, 0x10, left),
        write_register(rdsd1, ADDR_DAC_RIGHT, 0x07, 0x00, 0x00, 0x00, right),
        write_register(rdsd2, ADDR_DAC_RIGHT, 0x07, 0x00, 0x01, 0x00, right),
        write_two_byte_offset(_SEQ_VOL_AGG_RIGHT, ADDR_AGGREGATE, 0x00, 0x11, right),
    ]
