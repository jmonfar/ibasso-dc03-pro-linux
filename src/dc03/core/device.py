"""hidraw I/O for the DC03 Pro.

Open the device, send batches of output reports with the required 20 ms
gap, and read raw input reports. Higher-level operations (apply a volume
change, parse a marker, persist to config) live in code that consumes this
module.

There is intentionally no autodiscovery / scanning function — see
`docs/design.md`. The device path is provided by the caller (CLI flag or
config file), and `validate_hidraw_path` verifies it before use.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from . import protocol

INTER_REPORT_DELAY_S = 0.020

DEFAULT_SYS_ROOT = Path("/sys")


def validate_hidraw_path(
    path: Path | str,
    sys_root: Path | str | None = None,
) -> bool:
    """Return True iff `path` is a hidraw node belonging to a DC03 Pro.

    Both checks must pass:
      1. The path exists on disk.
      2. The matching sysfs entry's `device/uevent` file declares VID/PID
         `262A:187E`.

    `sys_root` defaults to `DEFAULT_SYS_ROOT` (looked up at call time so tests
    can monkeypatch the module attribute).
    """
    path = Path(path)
    if not path.exists():
        return False

    if sys_root is None:
        sys_root = DEFAULT_SYS_ROOT
    uevent = Path(sys_root) / "class" / "hidraw" / path.name / "device" / "uevent"
    if not uevent.is_file():
        return False

    for line in uevent.read_text().splitlines():
        parsed = _parse_hid_id(line)
        if parsed is None:
            continue
        _, vid, pid = parsed
        return vid == protocol.VENDOR_ID and pid == protocol.PRODUCT_ID
    return False


def send_batch(
    path: Path | str,
    reports: list[bytes],
    gap: float = INTER_REPORT_DELAY_S,
) -> None:
    """Write a sequence of 16-byte output reports to the hidraw node.

    Each report is prefixed with a `\\x00` report-ID byte (17 bytes per
    write). A `gap`-second pause separates consecutive writes — the device
    needs ~20 ms between reports of a multi-report transaction, see
    `docs/protocol.md`.

    All reports are size-validated up front so a bad report aborts the whole
    batch before any I/O. An empty `reports` list is a no-op (the device
    node is not even opened).
    """
    if not reports:
        return

    for i, report in enumerate(reports):
        if len(report) != protocol.OUTPUT_REPORT_SIZE:
            raise ValueError(
                f"report {i} is {len(report)} bytes, "
                f"expected {protocol.OUTPUT_REPORT_SIZE}"
            )

    fd = os.open(str(path), os.O_WRONLY)
    try:
        last = len(reports) - 1
        for i, report in enumerate(reports):
            os.write(fd, b"\x00" + report)
            if i < last:
                time.sleep(gap)
    finally:
        os.close(fd)


def read_input_report(fd: int) -> bytes:
    """Read one 32-byte input report from an open hidraw file descriptor."""
    return os.read(fd, protocol.INPUT_REPORT_SIZE)


def _parse_hid_id(line: str) -> tuple[int, int, int] | None:
    """Parse `HID_ID=BBBB:VVVVVVVV:PPPPPPPP` into `(bus, vid, pid)`."""
    if not line.startswith("HID_ID="):
        return None
    parts = line.split("=", 1)[1].split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0], 16), int(parts[1], 16), int(parts[2], 16)
    except ValueError:
        return None
