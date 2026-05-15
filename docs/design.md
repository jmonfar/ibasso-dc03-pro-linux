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
USB attach      →   udev rule        →   systemd user service   →   dc03 restore
USB detach      →   udev rule        →   systemd user service   →   dc03 forget
system resume   →   sleep targets    →   systemd user service   →   dc03 restore
user input      →                                                   dc03 <cmd>
```

Why a systemd user service in the middle:

- udev's `RUN+=` runs as root, but the config file we write/read lives in
  the seat user's `~/.config/dc03/`. A per-user systemd template service
  (`dc03-restore@.service`, triggered via `SYSTEMD_USER_WANTS`) lets the
  CLI run as the seat user with the right HOME and XDG dirs already set.
- Standard desktop integration pattern (used by many USB-peripheral tools).

The same udev rule that triggers the service also applies `TAG+="uaccess"`,
giving the seat user direct hidraw access without a custom group.

### Resume from suspend / hibernate

Hibernation cuts USB bus power, so the DAC cold-boots on resume. The kernel
re-enumerates USB and *usually* fires a fresh `add` event, which runs
`dc03 restore` via the existing udev path. But this isn't guaranteed across
every kernel + USB-controller combo, and any general settings that aren't
NVRAM-persisted on the device (see open questions in `protocol.md`) would
silently revert if the restore didn't fire.

To close the gap, a plain user unit `dc03-resume.service` hooks into
`sleep.target` / `suspend.target` / `hibernate.target` post-actions and
invokes `dc03 restore` (with no `--device` argument) on every wakeup. The
CLI resolves the path from `device.toml`, validates it against sysfs, and
either re-applies settings (when the path is still valid) or exits quietly
(letting the eventual udev `add` event do the work when the path is stale).
Either way, the end state is correct.

Cost: one extra unit file, plus an occasional redundant ~300 ms replay when
both triggers fire on the same wakeup. Idempotent and unnoticeable.

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

Restore is per-control: `dc03 restore` looks at each setting individually
(filter, gain, output, balance, volume) and pushes only the ones the user
has explicitly configured. On first connection nothing is configured, so
the device's current state is preserved untouched — only `device.toml`
gets recorded. Each `dc03 <control> <value>` invocation adds that one
control to the replay set without changing the others; the on-disk
`general.toml` represents the *set* of explicitly-set controls, not a
full record (`None` means "user has never set this").

`dc03 balance N` is the one exception: because changing balance requires
re-sending the full volume transaction, it errors out if no volume has
been set yet. The user runs `dc03 volume N` first.

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
- `systemd/dc03-restore@.service`, `systemd/dc03-forget@.service`, and
  `systemd/dc03-resume.service` — user-level units that invoke the CLI.
  The `@.service` ones are templates fired by udev with the device path
  as the instance argument; `dc03-resume.service` is a plain unit hooked
  into `sleep.target` / `suspend.target` / `hibernate.target`
  post-actions.
- An installer / `make install` target that places these in
  `/etc/udev/rules.d/` and `~/.config/systemd/user/` (or the equivalent
  XDG location), then reloads udev.

## Distribution

How users are expected to install once the tool stabilises.

### Recommended end-user flow

```sh
uv tool install dc03-pro
dc03 install-system
```

`uv tool install` places the `dc03` console script in `~/.local/bin/`
(reliably on the user systemd manager's PATH on modern distros) inside an
isolated venv that uv manages. It also fetches a matching Python
interpreter if the system one doesn't satisfy `requires-python`.

`dc03 install-system` is a subcommand we plan to add (it does not exist
yet — see below). It does what `scripts/install.sh` does today: places the
udev rule and three systemd user units, reloads both daemons, enables the
resume hook. The difference is that the subcommand reads the files from
package data (`importlib.resources`) inside the installed wheel rather than
from a repo checkout, so users don't need the source tree.

### Alternative: pipx

```sh
pipx install dc03-pro
dc03 install-system
```

Equivalent UX, still supported. Not the primary recommendation because uv
is the direction Python tooling is moving and we already use it for
development — one tool, one mental model. pipx stays in the README as a
fallback for users who already have it installed.

### Hacking on the tool

```sh
git clone <repo>
cd ibasso-dc03-pro-linux
uv sync
ln -s "$PWD/.venv/bin/dc03" ~/.local/bin/dc03   # editable install + on PATH
./scripts/install.sh                            # udev + systemd plumbing
```

The symlink makes the editable `.venv/bin/dc03` reachable from the user
systemd manager's PATH. Edits to `src/dc03/` take effect on next CLI
invocation without reinstall. `uv tool install` is the wrong choice for
this flow because it makes a frozen copy.

### What changes in the repo when we ship

- `pyproject.toml` grows a wheel-data section
  (`[tool.hatch.build.targets.wheel.force-include]` or `shared-data`)
  including `udev/*.rules` and `systemd/*.service` so they ride along in
  the installed package.
- The CLI gains `install-system` / `uninstall-system` subcommands. The
  current `scripts/install.sh` / `scripts/uninstall.sh` stay for the
  hacking flow but stop being the recommended end-user path.
- A first release goes to PyPI.

### Explicitly not pursued

- **deb/rpm/AUR packages of our own.** Audience is niche; per-distro
  packaging is busy-work. Happy to accept community packagers if anyone
  steps up.
- **Flatpak/Snap.** Incompatible with the integration: the sandbox blocks
  writing udev rules and triggering user systemd units across the bus.
- **`curl … | sh` installer.** Security smell, and `uv tool install` is
  already one line.

### When to do this

After real-device shakedown confirms the udev/systemd integration actually
behaves as designed (attach → restore, detach → forget, resume → restore).
Until then, the repo-based install (`scripts/install.sh`) is the right
level of investment.

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
