"""hidraw I/O for the DC03 Pro.

Open, read, write. Higher-level operations (apply a volume change, parse an
input report stream) live in code that consumes this module.
"""

from __future__ import annotations

from pathlib import Path

from . import protocol

INTER_REPORT_DELAY_S = 0.020


def find_hidraw() -> Path | None:
    """Return the /dev/hidrawN node matching VID/PID, or None if not present."""
    raise NotImplementedError


def send_batch(path: Path, reports: list[bytes]) -> None:
    """Write a sequence of 16-byte reports with the required gap between each.

    Each report must be prefixed with a 0x00 report-ID byte when written
    through /dev/hidrawN (total 17 bytes per write).
    """
    raise NotImplementedError


def read_input_report(fd: int) -> bytes:
    """Read one 32-byte input report from the hidraw fd."""
    raise NotImplementedError
