#!/usr/bin/env python3
"""dc03-gui — Tkinter front-end for the dc03 CLI.

Stopgap personal tool, not part of the dc03 installed package. All
state operations go through the CLI:
  - reads current state via `dc03 <ctrl> --read`
  - applies changes via `dc03 <ctrl> <value>` or `dc03 <ctrl> --unset`
  - detects connection via sysfs grep for the DC03's VID:PID

Run with `python3 contrib/dc03-gui.py` from a checkout, or copy anywhere
and run directly. Requires:
  - `dc03` on PATH (the v0.2+ CLI; this uses `--read` / `--unset`).
  - Python's tkinter module (stdlib, but some standalone Python builds
    omit it on Linux). If your default `python3` lacks tkinter, install
    your distro's tkinter package:
        Debian/Ubuntu/Mint: sudo apt install python3-tk
        Fedora:             sudo dnf install python3-tkinter
        Arch:               sudo pacman -S tk
    …or run with the system Python explicitly:
        /usr/bin/python3 contrib/dc03-gui.py
"""

from __future__ import annotations

import glob
import re
import subprocess
import sys

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    sys.stderr.write(
        "dc03-gui: Python's tkinter module is not available in this Python.\n"
        "Install your distro's python3-tk package, or run with /usr/bin/python3.\n"
        "See the docstring at the top of this file for details.\n"
    )
    sys.exit(1)

# Presumed device defaults — shown next to "(Keep device default ...)"
# entries in each dropdown. Source:
#   filter:  fast-rolloff (presumed; matches the Android UAC app default)
#   gain:    high         (empirically confirmed power-on default)
#   output:  normal       (presumed; matches the Android UAC app default)
PRESUMED_DEFAULTS = {
    "filter": "fast-rolloff",
    "gain":   "high",
    "output": "normal",
}

FILTER_VALUES = [
    "fast-rolloff",
    "slow-rolloff",
    "short-delay-fast",
    "short-delay-slow",
    "nos",
]
GAIN_VALUES = ["low", "medium", "high"]
OUTPUT_VALUES = ["normal", "turbo"]


def keep_default_label(control: str) -> str:
    return f"(Keep device default — {PRESUMED_DEFAULTS[control]})"


def device_connected_path() -> str | None:
    """Return /dev/hidrawN if a DC03 Pro is attached, else None."""
    for uevent in glob.glob("/sys/class/hidraw/*/device/uevent"):
        try:
            with open(uevent) as f:
                content = f.read()
        except OSError:
            continue
        if re.search(r"0+262a:0+187e", content, re.IGNORECASE):
            m = re.search(r"/hidraw(\d+)/device/uevent$", uevent)
            if m:
                return f"/dev/hidraw{m.group(1)}"
    return None


def run_dc03(*args: str) -> tuple[int, str, str]:
    """Invoke `dc03 ...`. Returns (returncode, stdout, stderr)."""
    proc = subprocess.run(
        ["dc03", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def read_control(control: str) -> str | None:
    """Read a control's current value via `dc03 <ctrl> --read`. None if unset."""
    rc, out, _err = run_dc03(control, "--read")
    if rc != 0 or not out:
        return None
    return out


class DC03GUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("DC03 Pro Control")
        root.resizable(False, False)

        # Tk variables for widget state.
        self.status_var = tk.StringVar()
        self.filter_var = tk.StringVar()
        self.gain_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.volume_var = tk.IntVar(value=75)
        self.balance_var = tk.IntVar(value=0)
        self.volume_label_var = tk.StringVar(value="75")
        self.balance_label_var = tk.StringVar(value="0")
        self.action_var = tk.StringVar(value="ready")

        # Snapshot of state at last refresh, for dirty-detection on apply.
        # filter/gain/output:  the value name or None (= unset / sentinel)
        # volume/balance:      int or None
        self._snapshot: dict[str, object | None] = {}

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 4}

        # ---- Status line + Refresh ----
        status_frame = ttk.Frame(self.root)
        status_frame.grid(row=0, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Label(
            status_frame,
            text="Status:",
            font=("TkDefaultFont", 9, "bold"),
        ).pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Button(
            status_frame, text="Refresh", command=self.refresh, width=8
        ).pack(side=tk.RIGHT)

        ttk.Separator(self.root).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=8
        )

        # ---- General-settings dropdowns (filter / gain / output) ----
        controls = [
            ("filter", FILTER_VALUES),
            ("gain", GAIN_VALUES),
            ("output", OUTPUT_VALUES),
        ]
        for i, (control, values) in enumerate(controls):
            ttk.Label(self.root, text=f"{control.capitalize()}:").grid(
                row=2 + i, column=0, sticky="w", **pad
            )
            options = [keep_default_label(control)] + values
            var = getattr(self, f"{control}_var")
            ttk.Combobox(
                self.root,
                textvariable=var,
                values=options,
                state="readonly",
                width=34,
            ).grid(row=2 + i, column=1, sticky="ew", **pad)

        ttk.Separator(self.root).grid(
            row=5, column=0, columnspan=2, sticky="ew", padx=8
        )

        # ---- Volume / balance sliders ----
        self._add_slider(
            row=6,
            label="Volume:",
            var=self.volume_var,
            label_var=self.volume_label_var,
            from_=0,
            to=100,
        )
        self._add_slider(
            row=7,
            label="Balance:",
            var=self.balance_var,
            label_var=self.balance_label_var,
            from_=-50,
            to=50,
        )

        ttk.Separator(self.root).grid(
            row=8, column=0, columnspan=2, sticky="ew", padx=8
        )

        # ---- Apply button + action message ----
        button_frame = ttk.Frame(self.root)
        button_frame.grid(row=9, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Button(
            button_frame, text="Apply", command=self.apply, width=10
        ).pack(side=tk.LEFT)
        ttk.Label(
            button_frame, textvariable=self.action_var, foreground="grey"
        ).pack(side=tk.LEFT, padx=12)

        self.root.columnconfigure(1, weight=1)

    def _add_slider(
        self,
        row: int,
        label: str,
        var: tk.IntVar,
        label_var: tk.StringVar,
        from_: int,
        to: int,
    ) -> None:
        pad = {"padx": 10, "pady": 4}
        ttk.Label(self.root, text=label).grid(
            row=row, column=0, sticky="w", **pad
        )
        frame = ttk.Frame(self.root)
        frame.grid(row=row, column=1, sticky="ew", **pad)
        ttk.Scale(
            frame,
            from_=from_,
            to=to,
            orient=tk.HORIZONTAL,
            variable=var,
            command=lambda v, lv=label_var: lv.set(str(int(float(v)))),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(frame, textvariable=label_var, width=4, anchor="e").pack(
            side=tk.LEFT
        )

    # ---- State sync ----

    def refresh(self) -> None:
        """Reload from sysfs + `dc03 ... --read`."""
        path = device_connected_path()
        self.status_var.set(
            f"● Connected ({path})" if path else "○ Not connected"
        )

        # Dropdown controls
        for control in ("filter", "gain", "output"):
            val = read_control(control)
            self._snapshot[control] = val
            var = getattr(self, f"{control}_var")
            var.set(val if val is not None else keep_default_label(control))

        # Volume slider — show stored value if any, else 75 default
        vol = read_control("volume")
        vol_int = self._parse_int(vol, default=75)
        self.volume_var.set(vol_int)
        self.volume_label_var.set(str(vol_int))
        self._snapshot["volume"] = self._parse_int(vol, default=None)

        # Balance slider — show stored value if any, else 0
        bal = read_control("balance")
        bal_int = self._parse_int(bal, default=0)
        self.balance_var.set(bal_int)
        self.balance_label_var.set(str(bal_int))
        self._snapshot["balance"] = self._parse_int(bal, default=None)

        self.action_var.set("state loaded")

    @staticmethod
    def _parse_int(s: str | None, default):
        if s is None or s == "":
            return default
        try:
            return int(s)
        except ValueError:
            return default

    # ---- Apply ----

    def apply(self) -> None:
        """Compare current widget state to snapshot; run dc03 for each diff."""
        actions: list[str] = []
        errors: list[str] = []
        # Controls that were transitioned from "set" → "Keep device default".
        # Their stored preference is cleared but the device retains the
        # previous value until power-cycled — surface that to the user.
        unset_warnings: list[str] = []

        # filter / gain / output: sentinel ↔ value transitions
        for control in ("filter", "gain", "output"):
            current = getattr(self, f"{control}_var").get()
            current_is_sentinel = current == keep_default_label(control)
            target = None if current_is_sentinel else current
            previous = self._snapshot.get(control)
            if target == previous:
                continue
            if target is None:
                rc, out, err = run_dc03(control, "--unset")
                actions.append(f"{control}=cleared")
                if rc == 0 and previous is not None:
                    unset_warnings.append(
                        f"{control.capitalize()}: stored preference cleared, "
                        f"but the device still has \"{previous}\" applied. "
                        f"To revert to the hardware default "
                        f"({PRESUMED_DEFAULTS[control]}), unplug and replug "
                        f"the DAC."
                    )
            else:
                rc, out, err = run_dc03(control, target)
                actions.append(f"{control}={target}")
            if rc != 0:
                errors.append(f"{control}: {err or out}")

        # Volume
        target_vol = self.volume_var.get()
        if target_vol != self._snapshot.get("volume"):
            rc, out, err = run_dc03("volume", str(target_vol))
            actions.append(f"volume={target_vol}")
            if rc != 0:
                errors.append(f"volume: {err or out}")

        # Balance — the slider always has a value, so we only diff against
        # snapshot. If snapshot was None and slider is at 0, that's not
        # technically a change (both effectively unset). Don't push it.
        target_bal = self.balance_var.get()
        prev_bal = self._snapshot.get("balance")
        if target_bal != prev_bal and not (prev_bal is None and target_bal == 0):
            rc, out, err = run_dc03("balance", str(target_bal))
            actions.append(f"balance={target_bal}")
            if rc != 0:
                errors.append(f"balance: {err or out}")

        if errors:
            self.action_var.set("error: " + "; ".join(errors))
        elif actions:
            self.action_var.set("applied: " + ", ".join(actions))
        else:
            self.action_var.set("nothing to apply")

        if unset_warnings:
            messagebox.showwarning(
                "Stored preference cleared — device unchanged",
                "\n\n".join(unset_warnings),
            )

        self.refresh()


def main() -> None:
    root = tk.Tk()
    DC03GUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
