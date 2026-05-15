"""Bundled data files (udev rule + systemd unit templates).

Accessed at runtime via `importlib.resources.files("dc03._data")` from the
`install-system` / `uninstall-system` CLI subcommands. This is just an
anchor package; the actual files live under `udev/` and `systemd/`
subdirectories.
"""
