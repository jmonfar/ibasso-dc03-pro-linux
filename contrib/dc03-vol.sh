#!/bin/sh
# dc03-vol — print "DC03pro vol N" when a DC03 Pro is attached, or
# "DC03pro absent" otherwise. For status widgets (e.g. Cinnamon
# CommandRunner). Personal tool; not part of the dc03 installed package.

# Presence check: any hidraw node whose sysfs uevent carries the DC03 Pro's
# VID:PID (262A:187E). ~1-2 ms over a handful of small files.
if ! grep -qi "262a:0000187e" /sys/class/hidraw/*/device/uevent 2>/dev/null; then
    echo "DC03pro absent"
    exit 0
fi

# DC03 is attached. Ask the CLI for the stored volume. Requires the v0.2+
# CLI for the --read flag; on v0.1 the same effect needed an awk parse of
# $XDG_CONFIG_HOME/dc03/volume.toml.
volume=$(dc03 volume --read 2>/dev/null)

if [ -n "$volume" ]; then
    echo "DC03pro vol $volume"
else
    echo "DC03pro vol —"
fi
