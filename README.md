# DC03 Pro Control for Linux

Unofficial Linux controller for the **iBasso DC03 Pro** USB DAC.

Not affiliated with, endorsed by, or supported by iBasso.

## Status

Early work in progress. Protocol research complete; CLI implemented; not yet
shaken out on a wide range of hardware.

## Install

The CLI itself runs from a uv-managed virtualenv (`uv sync` once, then
`uv run dc03 --help`). To wire it up so settings persist and replay
automatically across plug/unplug and resume:

```sh
uv sync
./scripts/install.sh        # places the udev rule and 3 systemd user units
```

What the installer does:

- Drops `udev/70-ibasso-dc03-pro.rules` into `/etc/udev/rules.d/` (sudo).
- Drops `dc03-restore@.service`, `dc03-forget@.service`, and
  `dc03-resume.service` into `~/.config/systemd/user/`.
- Reloads udev, enables the resume hook.

After install, plugging in the DC03 grants the seat user access to its
hidraw node and replays the stored settings. Unplugging clears the stored
device path. The CLI commands (`dc03 volume 50`, `dc03 filter nos`, etc.)
auto-resolve the device path from `~/.config/dc03/device.toml` written by
the attach handler.

`./scripts/uninstall.sh` reverses everything (leaving stored settings
behind).

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

## Supported Device

| Device | USB Vendor ID | USB Product ID |
| --- | --- | --- |
| iBasso DC03 Pro | `0x262a` | `0x187e` |

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgements

This project draws on protocol knowledge and reference code from
[ibasso-dc03-pro-macos](https://github.com/Chandru03/ibasso-dc03-pro-macos) by
Chandru03, used under the MIT License:

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
