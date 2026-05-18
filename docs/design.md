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
- `dc03 watch` — long-running input-report watcher. Reads `fe 01`
  events from the hidraw node and writes the recovered volume + balance
  into `volume.toml`. Intended to be invoked by udev on attach (alongside
  `restore`) so hardware-button changes stay in sync with the config.
- `dc03 forget` — clear the recorded device path. Manual cleanup only;
  see Disconnect handling for why we don't run it automatically.

Each per-control command (`volume`, `filter`, `gain`, `output`, `balance`)
takes either a value (set mode), `--read` (print the current persisted
value), or `--unset` (clear the setting from config; not available on
`volume` since the watcher keeps it populated). `--read` and `--unset`
operate purely on the config files and don't touch the device — useful
for status scripts and for the contributed GUI front-end. See
`CHANGELOG.md` v0.2 for details.

There is **no** separate daemon module. The "udev-triggered settings replay"
function originally pencilled in as `src/dc03/daemon/` is just the `restore`
subcommand of the CLI — it runs for ~300 ms and exits.

## Trigger model

```
USB attach      →   udev rule        →   systemd user service   →   dc03 restore
USB attach      →   udev rule        →   systemd user service   →   dc03 watch  (long-running)
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

Not handled. Hibernation cuts USB bus power and the DAC cold-boots, so
filter/gain/output reset to hardware defaults (volume and balance survive
in NVRAM). We initially shipped a `dc03-resume.service` user unit anchored
to `sleep.target` / `suspend.target` / `hibernate.target` post-actions
that would have re-pushed the lost settings, but empirically on the
tested kernel + USB-controller combo `journalctl` confirmed it never
fires — the user-manager's sleep-target integration stays inactive across
hibernation, and the kernel silently rebinds the device without emitting
a fresh udev `add` event. The unit was dead weight on every machine we
could observe, so it's been removed from the install bundle rather than
shipped as a feature that doesn't deliver.

Workaround for the user: physically unplug and replug the DAC after
resuming from hibernation. That forces a fresh udev `add` event and a
normal restore cycle. Documented in the README.

If we ever want to revisit this, the options would be:

- A `dc03-resume.service` that scans sysfs for `262A:187E` (re-introducing
  the autodiscovery logic we explicitly removed) rather than trusting
  `device.toml`, in case `dc03-resume.service` *does* fire on some distros
  and the device path has changed.
- A watcher that notices a state-reset on the device by observing
  register values that don't match what we sent, and self-triggers a
  restore. Requires being able to read register state, which we can't
  reliably do without input-report events.

Neither is in scope for v1.

## Device discovery

There is **no scan-based autodiscovery**. The device path propagates via
udev → config:

1. On attach, the udev rule invokes `dc03 restore --device $DEVNAME`, which
   writes `path = "$DEVNAME"` into `device.toml`.
2. On detach: nothing fires automatically (see Disconnect handling).
   `dc03 forget` is available as a manual cleanup subcommand.
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

Three TOML files under `~/.config/dc03/`, split by **whether the device
persists each value in its own NVRAM**. Each is written atomically
(tempfile + `rename`).

```
~/.config/dc03/
├── device.toml      # runtime detection state
│     path = "/dev/hidraw5"
│     attached_at = 2026-05-15T09:12:33+02:00
│
├── general.toml     # device does NOT persist these — replayed every attach
│     filter = 0
│     gain = 0
│     output = 0
│
└── volume.toml      # device persists these in NVRAM — replay is safety-net
      volume = 75
      balance = 0
      updated_at = 2026-05-15T09:14:01+02:00
```

Writers:

- `device.toml` — written by `dc03 restore` (on attach), deleted by
  `dc03 forget` (on detach).
- `general.toml` — written by `dc03 filter|gain|output` interactive
  subcommands. Read by `dc03 restore`. These controls reset to factory
  defaults on every power-cycle of the device, so `dc03 restore` is the
  *only* thing that keeps our preferences sticky across plug-unplug.
- `volume.toml` — written by `dc03 volume` and `dc03 balance`. Read by
  `dc03 restore`. The device retains volume and balance across
  power-cycles in NVRAM (balance is just asymmetric L/R values in the
  same multi-report transaction as volume; both attenuation registers
  persist), so the replay-on-attach behaviour is a safety net (in case
  the state drifted via hardware buttons or another host) rather than
  load-bearing. In future, also written by a hardware-button watcher
  that observes input reports with marker `fe 01` and updates the stored
  volume.

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

- The split mirrors device behaviour: `general.toml` controls reset on
  power-cycle and must be replayed; `volume.toml` controls persist on the
  device and need not be (but are re-asserted on attach anyway, as a
  safety net).
- A volume change from a future button-watcher should never risk
  corrupting the general settings — different cadences, different writers.
- Each writer touches one file, so atomic-rename suffices; no cross-file
  locking needed.

## Disconnect handling

There is intentionally no automatic disconnect handler in v1.

We tried wiring one up via a `ACTION=="remove"` udev rule that set
`SYSTEMD_USER_WANTS=dc03-forget@…service`. Empirically: the rule fires
correctly, the env var lands in the remove event with the right value,
and the `systemd` tag is present — but `systemd-udev` only consumes
`SYSTEMD_USER_WANTS` when a device unit becomes *active* (i.e. on `add`).
On `remove` the device unit goes inactive and no units are pulled in. The
env var is silently dropped. The only workaround would be to `RUN+=` a
shell script from udev running as root and then `runuser` into the seat
user — brittle, hard-coded to a single user, and out of scope.

Instead we accept the limitation and rely on validate-on-read:

- The CLI is one-shot. If the device disappears between flag parsing and
  write, the write fails with `EIO`/`ENODEV` and we surface that as a
  normal error.
- After a disconnect, `device.toml` retains the (now-stale) path until
  the next CLI invocation. `resolve_device_path` revalidates the path
  against sysfs on every call, so the first command after unplug errors
  cleanly with "Stored device path /dev/hidrawN is no longer valid".
- `dc03 forget` is still a CLI subcommand for users who want to clear the
  stale entry manually.
- The next replug fires the attach rule, `dc03 restore` runs, and
  `device.toml` is rewritten with the new path.

If a future tray UI or hardware-button-watcher process holds an open fd
across plug events, it will see `POLLHUP`/`EIO` on disconnect and can
reconnect via `pyudev` monitoring or a polling retry. That belongs to
whatever long-running component gets built later, not to v1.

## Install bundle

What gets shipped inside the wheel:

- The `dc03` console script (via uv / pyproject entry point).
- `src/dc03/_data/udev/70-ibasso-dc03-pro.rules` — `TAG+="uaccess"`
  plus a `SYSTEMD_USER_WANTS` entry that fires both attach-time services.
- `src/dc03/_data/systemd/dc03-restore@.service` and
  `dc03-watch@.service` — user-level templates fired by udev on attach
  with the device path (e.g. `hidraw5`) as the instance argument.
  `dc03-restore@` is a one-shot that replays stored settings;
  `dc03-watch@` is a long-running reader (Type=simple,
  Restart=on-failure) that streams hardware-button events into
  `volume.toml` and exits cleanly when the device disconnects.

The `dc03 install-system` / `dc03 uninstall-system` CLI subcommands
read these bundled files via `importlib.resources` and copy them into
their canonical locations (`/etc/udev/rules.d/` and the XDG user
systemd dir), invoking `sudo` only for the system-level udev step.

## Distribution

GitHub is the only distribution channel. No PyPI release; `uv` and
`pipx` both accept git URLs as install sources, which is good enough for
this audience.

### Recommended end-user flow

```sh
uv tool install --from git+https://github.com/jmonfar/ibasso-dc03-pro-linux@v0.1 dc03
dc03 install-system
```

`uv tool install` places the `dc03` console script in `~/.local/bin/`
(reliably on the user systemd manager's PATH on modern distros) inside an
isolated venv that uv manages. It also fetches a matching Python
interpreter if the system one doesn't satisfy `requires-python`. Pinning
to a tagged release (`@v0.1`) gives users a stable target.

`dc03 install-system` reads the bundled udev rule and systemd unit
templates from package data (`importlib.resources`) and copies them into
their canonical locations, invoking `sudo` only for the system-level
udev step.

### Alternative: pipx

```sh
pipx install git+https://github.com/jmonfar/ibasso-dc03-pro-linux@v0.1
dc03 install-system
```

Equivalent UX for users who already use pipx.

### Hacking on the tool

```sh
git clone https://github.com/jmonfar/ibasso-dc03-pro-linux
cd ibasso-dc03-pro-linux
uv sync
ln -s "$PWD/.venv/bin/dc03" ~/.local/bin/dc03   # editable install + on PATH
dc03 install-system
```

The symlink makes the editable `.venv/bin/dc03` reachable from the user
systemd manager's PATH. Edits to `src/dc03/` take effect on next CLI
invocation without reinstall. `uv tool install` is the wrong choice for
this flow because it makes a frozen copy.

### Explicitly not pursued

- **PyPI release.** Not worth the recurring overhead (version bumps,
  upload discipline, name-squatting risk) for a niche tool when
  `pip install git+URL` works just as well.
- **deb/rpm/AUR packages of our own.** Audience is niche; per-distro
  packaging is busy-work. Happy to accept community packagers if anyone
  steps up.
- **Flatpak/Snap.** Incompatible with the integration: the sandbox blocks
  writing udev rules and triggering user systemd units across the bus.
- **`curl … | sh` installer.** Security smell, and `uv tool install` is
  already one line.
- **CI / automated test runs on PR.** Low PR volume expected; manual
  `uv run pytest` before tagging is enough.

## Explicitly out of scope for v1

- Autodiscovery / fallback scanning when `--device` is omitted and config is
  empty. Error out instead — it's a corner case for an already-permissioned
  setup.
- Tray UI, status indicator, or any long-running graphical component.
- Multi-DC03 support. Single device assumed; second attach overwrites the
  first in `device.toml`.
