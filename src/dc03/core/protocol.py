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
    report[1] = 0x11
    report[2] = 0x88
    report[3] = device_address
    report[6] = 0x05
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
    report[1] = 0x11
    report[2] = 0xA0
    report[3] = device_address
    report[4] = offset1
    report[5] = offset2
    report[6] = 0x01
    report[7] = value
    return bytes(report)
