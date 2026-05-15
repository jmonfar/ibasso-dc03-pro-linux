# DC03 Pro Control — Linux design notes

Decisions taken about how the Linux port is structured, and why. Counterpart
to `protocol.md`: that file documents the device, this one documents the
software around it.

## Tools and entry points

A single CLI binary, `dc03`, with subcommands. No long-running process.

- `dc03 volume <0..100>` — interactive volume change.
- `dc03 filter <0..4>`, `dc03 gain <low|med|high>`, `dc03 output <normal|power-saving>`,
  `dc03 balance <-50..50>` — interactive control of the rare-change settings.
- `dc03 restore` — replay stored settings to the device. Intended to be
  invoked by udev on attach; also runnable by hand.
- `dc03 forget` — clear the recorded device path. Intended to be invoked by
  udev on detach.

There is **no** separate daemon module. The "udev-triggered settings replay"
function originally pencilled in as `src/dc03/daemon/` is just the `restore`
subcommand of the CLI — it runs for ~300 ms and exits.

## Trigger model

```
USB attach   →   udev rule   →   systemd user service   →   dc03 restore
USB detach   →   udev rule   →   systemd user service   →   dc03 forget
user input   →                                              dc03 <cmd>
```

Why a systemd user service in the middle:

- udev's `RUN+=` runs as root, but the config file we write/read lives in
  the seat user's `~/.config/dc03/`. A per-user systemd template service
  (`dc03-restore@.service`, triggered via `SYSTEMD_USER_WANTS`) lets the
  CLI run as the seat user with the right HOME and XDG dirs already set.
- Standard desktop integration pattern (used by many USB-peripheral tools).

The same udev rule that triggers the service also applies `TAG+="uaccess"`,
giving the seat user direct hidraw access without a custom group.

## Device discovery

There is **no scan-based autodiscovery**. The device path propagates via
udev → config:

1. On attach, the udev rule invokes `dc03 restore --device $DEVNAME`, which
   writes `path = "$DEVNAME"` into `device.toml`.
2. On detach, the udev rule invokes `dc03 forget`, which deletes
   `device.toml`.
3. All other CLI subcommands resolve the path in this order:
   1. `--device` flag if explicitly passed.
   2. `device.toml` contents if present.
   3. Otherwise: exit with a clear error ("DC03 not detected. Plug in the
      device, or pass --device explicitly.").

### Validate on read

Whenever a CLI subcommand resolves a path from `device.toml`, it
re-validates before using it: the node must exist on disk **and** its sysfs
entry (`/sys/class/hidraw/<n>/device/uevent`) must still contain
`HID_ID=…262A:187E`. If either check fails, treat as if the file were
absent — error out and let the next udev attach event refresh the config.

This is self-healing: stale state across reboots, missed udev events, or
manual config tampering all resolve themselves on the next plug.

## Config layout

Three TOML files under `~/.config/dc03/`, split by write-frequency and
writer identity. Each is written atomically (tempfile + `rename`).

```
~/.config/dc03/
├── device.toml      # runtime detection state
│     path = "/dev/hidraw5"
│     attached_at = 2026-05-15T09:12:33+02:00
│
├── general.toml     # rare-change user prefs (replayed on attach)
│     filter = 0
│     gain = 0
│     output = 0
│     balance = 0
│
└── volume.toml      # high-churn (CLI + future button-watcher widget)
      volume = 75
      updated_at = 2026-05-15T09:14:01+02:00
```

Writers:

- `device.toml` — written by `dc03 restore` (on attach), deleted by
  `dc03 forget` (on detach).
- `general.toml` — written by interactive CLI subcommands when the user
  changes a rare setting. Read by `dc03 restore`.
- `volume.toml` — written by `dc03 volume`. Read by `dc03 restore`. In
  future, also written by a hardware-button watcher that observes input
  reports with marker `fe 01` and updates the stored volume.

Why three files instead of one:

- A volume change from a future button-watcher should never risk corrupting
  the general settings — they're touched on different cadences.
- Each writer touches one file, so atomic-rename suffices; no cross-file
  locking needed.
- Schema-level concerns stay clean: runtime detection state is
  conceptually distinct from user preferences and from the current volume.

## Disconnect handling

No in-session disconnect detection is required in v1:

- The CLI is one-shot. If the device disappears between flag parsing and
  write, the write fails with `EIO`/`ENODEV`; we surface that as a normal
  error.
- The `restore` subcommand is one-shot — by the time the user unplugs, it
  has long exited.
- The detach rule clears `device.toml`, so subsequent CLI invocations cleanly
  error out with "DC03 not detected".

If a future tray UI or hardware-button-watcher process holds an open fd
across plug events, it will see `POLLHUP`/`EIO` on disconnect and can
reconnect via `pyudev` monitoring or a polling retry. That belongs to
whatever long-running component gets built later, not to v1.

## Install bundle

What gets shipped:

- The `dc03` console script (via uv / pyproject entry point).
- `udev/70-ibasso-dc03-pro.rules` — `TAG+="uaccess"` plus
  `ENV{SYSTEMD_USER_WANTS}` entries for attach/detach.
- `systemd/dc03-restore@.service` and `systemd/dc03-forget@.service`
  (user-level template units that invoke the CLI).
- An installer / `make install` target that places these in
  `/etc/udev/rules.d/` and `~/.config/systemd/user/` (or the equivalent
  XDG location), then reloads udev.

## Explicitly out of scope for v1

- Autodiscovery / fallback scanning when `--device` is omitted and config is
  empty. Error out instead — it's a corner case for an already-permissioned
  setup.
- Tray UI, status indicator, or any long-running graphical component.
- Hardware-button reactive state tracking (the `fe 01` input-report loop).
  The protocol and data flow are documented in `protocol.md`; the
  implementation is deferred.
- Multi-DC03 support. Single device assumed; second attach overwrites the
  first in `device.toml`.
