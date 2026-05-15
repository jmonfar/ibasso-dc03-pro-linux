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
