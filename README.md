# DC03 Pro Control for Linux

Unofficial Linux controller for the **iBasso DC03 Pro** USB DAC.

Not affiliated with, endorsed by, or supported by iBasso.

## Status

Early work in progress. Protocol research complete; CLI implemented; not yet
shaken out on a wide range of hardware.

## Install

One-line install, no clone needed — pinned to the tested v0.1 release:

```sh
uv tool install --from git+https://github.com/jmonfar/ibasso-dc03-pro-linux@v0.1 dc03
dc03 install-system
```

Or with pipx:

```sh
pipx install git+https://github.com/jmonfar/ibasso-dc03-pro-linux@v0.1
dc03 install-system
```

What `dc03 install-system` does:

- Drops `70-ibasso-dc03-pro.rules` into `/etc/udev/rules.d/` (prompts for sudo).
- Drops `dc03-restore@.service` and `dc03-watch@.service` into
  `~/.config/systemd/user/` (no sudo).
- Reloads udev and the user systemd daemon.

After install, plugging in the DC03 grants the seat user access to its
hidraw node and replays the stored settings. The CLI commands
(`dc03 volume 50`, `dc03 filter nos`, etc.) auto-resolve the device path
from `~/.config/dc03/device.toml` written by the attach handler.
Unplugs aren't automatically detected (a systemd limitation around udev
`remove` events — see `docs/design.md`); the next CLI invocation while
unplugged will report the stored path as no longer valid, and the next
replug rewrites it cleanly.

`dc03 uninstall-system` reverses everything (leaving stored settings
behind).

### Hacking on it

To run from a local checkout with edits taking effect immediately:

```sh
git clone https://github.com/jmonfar/ibasso-dc03-pro-linux
cd ibasso-dc03-pro-linux
uv sync
ln -s "$PWD/.venv/bin/dc03" ~/.local/bin/dc03
dc03 install-system
```

Editable install — changes to `src/dc03/` take effect on the next CLI
invocation, no rebuild step. `uv tool install` is the wrong choice for
this flow because it makes a frozen copy.

## How settings are managed

The CLI is deliberately unobtrusive: it only pushes settings to the device
that you have explicitly set. The point is to never silently overwrite
state the device was already holding from previous use.

- **First connection.** Plugging in the DAC for the first time (after the
  udev rule and systemd units are installed) does *not* alter its state.
  The attach hook records the device path under `~/.config/dc03/`; nothing
  is sent to the hardware.

- **Setting one control.** `dc03 filter nos` sends the filter change and
  remembers it in `~/.config/dc03/general.toml`. Volume, gain, output mode,
  and balance remain whatever the device already had.

- **Hardware buttons stay in sync.** A `dc03 watch` background process,
  fired by udev on attach, observes the device's input-report stream and
  records hardware volume-button presses into `volume.toml` (including
  any balance preserved across button presses). So the stored config
  reflects both CLI changes and physical button changes — useful for any
  later restore (e.g. after a replug) to re-assert the right value.

- **Subsequent plug-ins and resume-from-sleep.** Each replug and each
  wakeup replays only the controls you have set. If filter is the only
  thing you've ever set, only filter gets replayed.

- **What lives where.** `general.toml` holds settings the device does
  *not* keep across power-cycles (filter, gain, output mode) — these get
  replayed on every attach because the device forgets them on unplug.
  `volume.toml` holds settings the device *does* persist in NVRAM (volume
  and balance) — these would survive an unplug on their own; the CLI
  re-asserts them on attach as a safety net in case the state drifted
  (hardware buttons, another host).

- **Balance is coupled to volume.** Changing balance requires re-sending
  the full volume transaction, so `dc03 balance N` requires you to have
  set a volume first via `dc03 volume N`. Otherwise the command errors out
  rather than picking an arbitrary default volume and writing it.

To reset to "untouched": `rm -rf ~/.config/dc03/` and replug. The device
keeps volume and balance in NVRAM (those stay where you had them); filter,
gain, and output mode revert to their hardware defaults (gain in
particular jumps to "high" — heads up for sensitive IEMs).

## Hibernation caveat

After resuming from full hibernation (not from suspend), the DAC's
filter, gain, and output mode can revert to hardware defaults — volume
and balance are unaffected (they're in the device's NVRAM). The cause is
kernel/USB behaviour rather than anything we can fix in user space: on
some setups the kernel silently rebinds the device across hibernation
without firing a fresh udev `add` event, so our attach hook (which would
re-push the lost settings) never runs.

**Workaround:** physically unplug and replug the DAC after resuming.
That forces a fresh udev event and a normal restore cycle, putting your
filter/gain/output back where they were. (See `docs/design.md` for the
history of why we don't ship an automatic resume hook.)

## Supported Device

| Device | USB Vendor ID | USB Product ID |
| --- | --- | --- |
| iBasso DC03 Pro | `0x262a` | `0x187e` |

## Extras

- [`contrib/dc03-vol.sh`](contrib/dc03-vol.sh) — a tiny POSIX shell script
  that prints the current stored volume (e.g. `DC03pro vol 75`) or
  `DC03pro absent` if the DAC isn't plugged in. Drop into `~/bin/` and
  `chmod +x` for use with Cinnamon's CommandRunner or any other status
  widget that polls a command.

- [`contrib/dc03-gui.py`](contrib/dc03-gui.py) — a small Tkinter
  front-end. Dropdowns for filter / gain / output (each with a "Keep
  device default" sentinel that maps to `dc03 <ctrl> --unset`), sliders
  for volume and balance, an Apply button that fires the right
  `dc03` subcommands. Read-only operations (state on startup, Refresh
  button) use `dc03 <ctrl> --read` so the GUI doesn't need to know the
  config file layout. Run as `python3 contrib/dc03-gui.py` or just
  `contrib/dc03-gui.py` after `chmod +x`. Needs Python's tkinter
  module (stdlib but some Python builds omit it — see the docstring at
  the top of the file for distro-specific install hints).

Neither file is part of the installed package; they live in the repo for
convenience.

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgements

This project draws on protocol knowledge and reference code from
[ibasso-dc03-pro-macos](https://github.com/Chandru03/ibasso-dc03-pro-macos) by
Chandru03, used under the MIT License.

Built collaboratively with [Claude](https://www.anthropic.com/claude)
(Anthropic's AI assistant) — design discussions, protocol analysis,
implementation, tests, and documentation. The decisions, the audio
testing on real hardware, the empirical protocol findings, and the
final say on everything are mine.

---

[ibasso-dc03-pro-macos](https://github.com/Chandru03/ibasso-dc03-pro-macos)
license text in full:

> Copyright (c) 2026 Chandru03
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.
