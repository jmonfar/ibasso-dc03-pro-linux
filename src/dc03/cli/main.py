"""Command-line interface for DC03 Pro control."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dc03",
        description="Control the iBasso DC03 Pro USB DAC.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show device connection status.")

    set_vol = sub.add_parser("set-volume", help="Set hardware volume (0-100).")
    set_vol.add_argument("level", type=int)

    sub.add_parser("watch", help="Print events as the device emits them.")

    args = parser.parse_args(argv)
    raise NotImplementedError(f"command not implemented yet: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
