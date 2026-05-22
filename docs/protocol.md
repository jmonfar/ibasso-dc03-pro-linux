# DC03 Pro Protocol Notes

Notes on the USB-HID control protocol of the iBasso DC03 Pro.

Derived from:

- Reference code in
  [ibasso-dc03-pro-macos](https://github.com/Chandru03/ibasso-dc03-pro-macos)
  (MIT, (c) 2026 Chandru03).
- Empirical capture and behaviour testing on Linux against the device.

Where this document and the macOS reference differ, this document reflects
what was observed empirically.

## Device

| Field | Value |
| --- | --- |
| USB Vendor ID | `0x262A` |
| USB Product ID | `0x187E` |
| Control interface | 0 |
| HID usage page | `0x0C` (Consumer) |
| HID usage | `0x01` |
| Output report size | 16 bytes, report ID 0 |
| Input report size | 32 bytes, report ID 0 |

The audio playback path uses the standard USB Audio Class interface and is
handled by the kernel audio stack. This protocol covers only control writes
and state-change notifications.

## Linux access

`/dev/hidrawN` corresponds to the HID interface above. Identify with:

```sh
for n in /dev/hidraw*; do
  udevadm info "$n" | grep -q "262A:187E" && echo "$n"
done
```

Out of the box, hidraw nodes require root. A udev rule grants the desktop
session access without sudo:

```
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="262a", ATTRS{idProduct}=="187e", \
    MODE="0660", TAG+="uaccess"
```

Place in `/etc/udev/rules.d/70-ibasso-dc03-pro.rules`, then reload:

```sh
sudo udevadm control --reload && sudo udevadm trigger
```

## Output reports (host -> device)

All output reports are 16 bytes, report ID 0. When writing through
`/dev/hidrawN` the buffer **must be 17 bytes**: a leading `\x00` byte for
the report ID, followed by the 16-byte payload.

Two report shapes are in use.

### Standard register write

```
byte  0    seq             per-write sequence number
byte  1    0x11            constant
byte  2    0x88            constant
byte  3    deviceAddress   I2C-like target (0x60 left DAC, 0x62 right DAC)
byte  4    0x00            constant
byte  5    0x00            constant
byte  6    0x05            constant
byte  7    offset1
byte  8    offset2
byte  9    offset3
byte 10    offset4
byte 11    value
byte 12-15 0x00            padding
```

### Two-byte-offset variant (used for the 0xA2 address space)

```
byte  0    seq
byte  1    0x11
byte  2    0xA0            constant (differs from 0x88)
byte  3    deviceAddress   typically 0xA2
byte  4    offset1
byte  5    offset2
byte  6    0x01            constant
byte  7    value
byte 8-15  0x00            padding
```

## Input reports (device -> host)

32 bytes:

```
byte  0-3   0x00            header/zero
byte  4-5   marker          report-type discriminator
byte  6-7   seq echo        16-bit LE; matches seq of the write being
                            acknowledged, or 0x0000 for non-write events
byte  8     L attenuation   left-channel attenuation register on `fe 01`
                            frames (fresh); stale cache of the last
                            `fe 01` byte 8 on `00 00` echoes (see marker
                            table below)
byte  9     R attenuation   right-channel attenuation register; same
                            semantics as byte 8. Equal to byte 8 when
                            balance=0; differs when balance≠0
byte 10-31  0x00            padding
```

### Marker semantics

| Marker (bytes 4-5) | Byte 8 (L attenuation) | Byte 9 (R attenuation) | Meaning |
| --- | --- | --- | --- |
| `fe 01` | **Fresh L register.** | **Fresh R register.** Equal to byte 8 when balance=0; differs otherwise. Recover user-facing volume as `volume_from_attenuation(max(L, R))` and balance as `L - R` (signed). Reliable for state tracking. | External state change — typically a hardware volume-button press. Buttons step both registers in lock-step, preserving any current balance offset (empirically verified). |
| `00 00` | **Stale cache of the last `fe 01` byte 8 value.** | **Stale cache of the last `fe 01` byte 9 value.** Host writes do *not* refresh either; both are zero until the first button event since attach. | Echo response to a host write. The useful field is `seq_echo` (per-write ack); bytes 8 and 9 are decoration. |

A third frame, also marker `00 00` but with `seq_echo == 0x0000`, is
non-deterministically interleaved mid-transaction during a volume change.
Empirically: zero to two of these per 10-report burst, appearing at
varying positions across bursts. Probably an internal commit notification.
Safe to ignore for state tracking.

## Volume / attenuation

The DAC attenuation register is a single byte:

- `0x00` = loudest (no attenuation)
- `0xFF` = silent (max attenuation)

The hardware buttons step the register through 101 discrete values mapped
to user-facing volume 0..100. The table is non-linear (5-unit register
steps at the quiet end, 1-unit steps in the middle and loud regions) and
is reproduced as `VOLUME_STEPS` in `dc03.core.protocol`.

## Multi-report transactions

A volume change cannot be applied with a single output report. A single
write to e.g. `(0x60, 0x09, 0x00, 0x01, 0x00)` is acknowledged by the
device (an echo report is emitted) but does **not** change the audio
output. Empirically the device commits a volume change only after the full
**ten-report** transaction below, sent with ~20 ms between each report:

| # | seq | Address | Offsets | Purpose |
| ---: | :---: | :---: | :--- | :--- |
| 1 | 0x01 | 0x60 | 0x09, 0, 1, 0 | left PCM ch1 |
| 2 | 0x02 | 0x60 | 0x09, 0, 2, 0 | left PCM ch2 |
| 3 | 0x03 | 0x62 | 0x09, 0, 1, 0 | right PCM ch1 |
| 4 | 0x04 | 0x62 | 0x09, 0, 2, 0 | right PCM ch2 |
| 5 | 0x09 | 0x60 | 0x07, 0, 0, 0 | left DSD 0 |
| 6 | 0x0A | 0x60 | 0x07, 0, 1, 0 | left DSD 1 |
| 7 | 0x13 | 0xA2 | 0, 0x10 (two-byte) | left aggregate |
| 8 | 0x0B | 0x62 | 0x07, 0, 0, 0 | right DSD 0 |
| 9 | 0x0C | 0x62 | 0x07, 0, 1, 0 | right DSD 1 |
| 10 | 0x14 | 0xA2 | 0, 0x11 (two-byte) | right aggregate |

The `value` byte (= target attenuation register) is the same across all ten
reports for an equal-channel (balance 0) volume change. For asymmetric
balance, the sequence numbers and per-channel values shift to alternate
sets — see `volumeReports()` in the macOS reference.

Filter, gain, and output-mode changes use two reports each (left + right
DAC). They are believed to require the same multi-report-commit rule but
**not yet verified empirically on Linux.**

## Per-control reports

These come from the macOS reference; values verified for the volume path
only.

### Digital filter

| Field | Value |
| --- | --- |
| seq | 0x11 (left), 0x12 (right) |
| address | 0x60 / 0x62 |
| offsets | 0x09, 0, 0, 0 |
| value | filter index, 0..4 |

Filter index meanings: 0 fast roll-off, 1 slow roll-off, 2 short delay fast,
3 short delay slow, 4 NOS.

### Gain

| Field | Value |
| --- | --- |
| seq | 0x15 (left), 0x16 (right) |
| address | 0x60 / 0x62 |
| offsets | 0x08, 0, 0, 0 |
| value | 0x00 low, 0x20 medium, 0x31 high |

### Output mode

Two modes exposed by iBasso's Android UAC app as **Normal** (register
`0x1C`) and **Turbo** (register `0x1E`). The exact electrical difference
isn't documented anywhere we have access to; on tested efficient
headphones the audible difference is subtle to imperceptible. Plausibly
a higher output-drive mode that only matters under hard load
(high-impedance / low-sensitivity transducers), but we haven't
characterised it.

| Field | Value |
| --- | --- |
| seq | 0x17 (left), 0x18 (right) |
| address | 0x60 / 0x62 |
| offsets | 0x0B, 0, 0, 0 |
| value | 0x1C normal, 0x1E turbo |

The macOS reference project (`ibasso-dc03-pro-macos`) labelled mode 1 as
"Power saving", which is electrically the wrong direction and conflicts
with iBasso's own labelling — we renamed to "turbo" in v0.2.1.

## Persistence across unplug

Tested by plugging into one USB port, setting state, unplugging, waiting
>5 s, and replugging.

| Setting | Persists across unplug? |
| --- | --- |
| Volume | **Yes** — stored in MCU NVRAM. |
| Balance | **Yes** — almost certainly stored as separate L/R attenuation registers in the same NVRAM as volume, given the protocol encodes balance as asymmetric L/R values in the volume transaction. |
| Gain | **No** — confirmed empirically. Hardware default on power-up is "high" (`0x31`). |
| Digital filter | **Likely no** — audibly inconclusive on tested setup. The Android UAC app's default of `fast roll-off` (index 0) is the presumed hardware default. |
| Output mode | **Likely no** — not audibly tested on the available headphones. The Android UAC app's default of `normal` (`0x1C`) is the presumed hardware default. |

The official Android UAC app overrides the device's stored volume with its
own remembered value on every connect. There is no observed way to *read*
state from the device on cold connect — the only state-revealing reports
arrive after either a button press or a host write.

## State-tracking strategy

Given the constraints above, an app that wants to display accurate volume
should:

1. On USB attach, write an absolute volume to establish a known baseline.
2. Maintain in-app state from its own writes (the write echoes are stale —
   trust your own knowledge of what you sent).
3. Run a hidraw read loop. On any frame with marker `fe 01`, replace the
   in-app state by reverse-looking-up `byte[8]` in `VOLUME_STEPS`.
4. Ignore `00 00`-marker frames for state purposes; optionally use the
   seq-echo byte as a per-write ack.

## Open questions

- Confirm filter / gain / output-mode writes require the full 2-report
  transaction vs work with a single report.
- Confirm the hardware power-on defaults for filter and output mode
  (gain is empirically known to default to "high").
- Determine whether any handshake or init sequence is required after USB
  attach before writes are accepted (so far, none observed needed).
- Investigate other uses of the 0xA2 address space — only volume-related
  writes seen so far.
