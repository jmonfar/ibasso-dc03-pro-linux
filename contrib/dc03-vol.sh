#!/bin/sh
 # dc03-vol — print "DC03pro vol N" when a DC03 Pro is attached, or
 # "DC03pro absent" otherwise. For status widgets (e.g. Cinnamon
 # CommandRunner). Stopgap personal tool; not part of the dc03 project.

 CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dc03"
 VOLUME_FILE="$CONFIG_DIR/volume.toml"

 # Presence check: any hidraw node whose sysfs uevent carries the DC03 Pro's
 # VID:PID (262A:187E). ~1-2 ms over a handful of small files.
 if ! grep -qi "262a:0000187e" /sys/class/hidraw/*/device/uevent 2>/dev/null; then
   echo "DC03pro absent"
   exit 0
 fi

# DC03 is attached. Read the stored volume.
volume=""
if [ -f "$VOLUME_FILE" ]; then
  volume=$(awk -F= '
    /^[[:space:]]*volume[[:space:]]*=/ {
      gsub(/[[:space:]]/, "", $2)
      print $2
      exit
    }
  ' "$VOLUME_FILE")
fi

if [ -n "$volume" ]; then
  echo "DC03pro vol $volume"
else
  echo "DC03pro vol —"
fi
