#!/bin/sh
# Copy the panel firmware into an ESPHome config folder so the ESPHome
# Device Builder can build it (it only sees its own folder). Run after every
# firmware change, before building. Default target: Home Assistant's
# esphome folder.
set -e
here="$(cd "$(dirname "$0")/.." && pwd)"
target="${1:-/homeassistant/esphome}/room_tiles"
mkdir -p "$target"
# mirror: files removed here are removed there
rm -rf "$target.tmp"
cp -a "$here/firmware" "$target.tmp"
rm -rf "$target"
mv "$target.tmp" "$target"
echo "firmware -> $target"
# the generic images' device files (firmware/devices) beside it, where the
# ESPHome Device Builder lists them; only room-tiles-*.yaml, so nothing else
# in the folder is touched
config="$(dirname "$target")"
for old in "$config"/room-tiles-*.yaml; do  # (renamed / removed ones go)
  [ -e "$old" ] && [ ! -e "$here/firmware/devices/$(basename "$old")" ] && rm -f "$old" && echo "removed $old"
done
for f in "$here"/firmware/devices/room-tiles-*.yaml; do
  cp "$f" "$config/"
  echo "device -> $config/$(basename "$f")"
done
