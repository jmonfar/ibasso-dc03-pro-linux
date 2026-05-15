# DC03 Pro Control for Linux

Linux port of
[ibasso-dc03-pro-macos](https://github.com/Chandru03/ibasso-dc03-pro-macos),
the unofficial macOS menu bar controller for the iBasso DC03 Pro USB DAC.

## Primary references

- `docs/protocol.md` — authoritative byte-level protocol notes (frame
  layouts, marker semantics, multi-report commit rule, volume curve,
  persistence behaviour, open questions).
- `docs/design.md` — software architecture decisions (single-CLI model,
  udev → systemd user service trigger, device discovery via config not
  scan, three-file config layout, what's in/out of scope for v1).
- `src/dc03/core/protocol.py` — protocol constants, the `VOLUME_STEPS`
  table, and helpers that build the 16-byte output reports.

## Upstream macOS project

The Swift reference implementation that protocol findings were derived from
lives at:

  https://github.com/Chandru03/ibasso-dc03-pro-macos

Used under the MIT License. Attribution is in `README.md` and inline at copy
sites (e.g. `VOLUME_STEPS` in `protocol.py`).

## Architecture

Layered Python package under `src/dc03/`:

- `core/` — protocol constants, frame builders, hidraw I/O. Pure stdlib.
- `cli/` — argparse entry point exposed as the `dc03` console script.
  Includes the `restore` / `forget` subcommands invoked by udev on
  attach/detach via a systemd user service. There is no separate daemon
  module — see `docs/design.md`.

Project managed with [uv](https://github.com/astral-sh/uv). After clone:

```sh
uv sync
uv run dc03 --help
```

## Linux specifics worth remembering

- Output reports are 16 bytes, but writes through `/dev/hidrawN` must be
  prefixed with a `\x00` report-ID byte (17 bytes total per write).
- `/dev/hidrawN` requires root by default. A udev rule (see
  `docs/protocol.md`) grants the desktop session non-root access.
- Volume changes require the full 10-report transaction with ~20 ms gaps.
  Single writes are silently ignored by the firmware.
- Write echoes (`marker == 00 00`) report stale state — only button events
  (`marker == fe 01`) are trustworthy for state tracking.
