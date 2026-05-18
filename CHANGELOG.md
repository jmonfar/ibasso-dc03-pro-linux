# Changelog

## v0.2 — unreleased

CLI primitives for reading and clearing individual settings, enabling
cleaner status scripts and a forthcoming Tkinter GUI front-end.

### Added

- **`--read` flag** on `volume`, `filter`, `gain`, `output`, and `balance`
  subcommands. Prints the current persisted value to stdout (canonical
  name for filter/gain/output, integer for volume/balance), or an empty
  line when the setting is unset. Exit code 0 in both cases. Reads from
  config only — no device required, no hardware contact.

- **`--unset` flag** on `filter`, `gain`, `output`, and `balance`. Clears
  the corresponding key from config (`general.toml` or `volume.toml`).
  When the last field in a file is unset, the file is removed entirely
  so `load_general()` / `load_volume()` return `None` again (matching
  "user has never set anything" semantics). Idempotent: unsetting an
  already-unset field succeeds with a "was not set" message.

  `volume` has no `--unset`: the watcher keeps it populated whenever the
  device is connected, so unsetting it is meaningless.

### Changed

- Device resolution is now lazy in the control subcommands. `--read` and
  `--unset` never touch hardware, so they work when the device is
  disconnected — useful for status scripts and GUI initialisation.
- The CLI dispatch table was flattened: every subcommand handler takes
  only `args` and resolves the device internally when needed. No
  behaviour change for set/restore/watch.

### Internal

- `save_general()` now deletes `general.toml` when all fields are `None`
  (was previously a silent no-op). This matches the new "unset" path: a
  field cleared via `--unset` removes its line from the file; clearing
  the last field removes the file itself.

### Contrib

- **`contrib/dc03-gui.py`** — a small Tkinter front-end for the CLI.
  Dropdowns for filter / gain / output with a "Keep device default"
  sentinel (mapped to `--unset`), sliders for volume and balance, Apply
  button that fires the right `dc03` subcommand for each dirty control,
  Refresh button that re-reads state via `dc03 <ctrl> --read`. Stdlib
  only (tkinter); not part of the installed package; lives in `contrib/`
  alongside `dc03-vol.sh`.

## v0.1 — 2026-05-15

First tagged release. Feature-complete CLI controller for the iBasso
DC03 Pro on Linux.

### What works

- CLI subcommands: `volume`, `filter`, `gain`, `output`, `balance`,
  `restore`, `forget`, `watch`, `install-system`, `uninstall-system`.
- udev integration: attach fires a one-shot settings restore and a
  long-running button-event watcher.
- Hardware button events synced into `volume.toml`, including balance
  recovery from byte 8 / byte 9 of `fe 01` input reports.
- Per-control restore: only settings the user has explicitly set are
  replayed on attach. The device's NVRAM-persisted state (volume,
  balance) is preserved by default; first connection is a no-op replay.
- Three-file config layout under `~/.config/dc03/`, split by what the
  device persists on its own (`volume.toml`) vs what we must re-push on
  every attach (`general.toml`) vs runtime detection state
  (`device.toml`).
- Install via `uv tool install --from git+URL` or `pipx install
  git+URL`, then `dc03 install-system`. No PyPI required.

### Known limitations (documented)

- **Hibernation**: the user-manager's sleep targets don't fire on the
  tested kernel/systemd combo, and the kernel silently rebinds the
  device across hibernation. Manual unplug+replug after resume is the
  documented workaround.
- **Disconnect not actively detected**: systemd's
  `SYSTEMD_USER_WANTS` only fires user units on `add` events. Stale
  `device.toml` paths are caught by validate-on-read in the CLI on the
  next invocation.
- **Filter / output persistence**: presumed-no per Android UAC defaults,
  not 100% empirically confirmed (gain is empirically confirmed
  not-persistent — defaults to "high" on power-on).
- **Single-DC03 only**: a second attach overwrites the first in
  `device.toml`.

### Empirical protocol findings encoded

- Volume and balance persist on device NVRAM across power cycles.
- Gain resets to "high" (`0x31`) on every power-on.
- Hardware buttons step both L and R attenuation registers in
  lock-step, preserving any current balance offset.
- `fe 01` input reports carry the L attenuation register in byte 8 and
  the R attenuation register in byte 9; these are independent (not
  mirrored) when balance ≠ 0.
- `00 00` echo reports carry a stale cache of the last `fe 01` byte 8 /
  byte 9 values; host writes do not refresh the cache.
- Mid-transaction "commit notification" frames (marker `00 00`,
  `seq_echo == 0x0000`) appear non-deterministically inside the 10-report
  volume transaction. Safe to ignore.

### Tooling

- Zero runtime dependencies; CPython ≥ 3.11 (uses stdlib `tomllib`).
- 104 tests via pytest (`uv run pytest`); all pass.

### Credit

Built with AI-assisted pair programming throughout (Claude, Anthropic).
Decisions, real-hardware testing, and final responsibility are the
human author's.
