# Room Tiles panel firmware

ESPHome firmware for wall panels (Elecrow CrowPanel Advanced ESP32-P4, all
1024x600). Work in progress - see `docs/TODO.md` "Step 3".

- `room_tiles.yaml` - the panel (one firmware per board)
- `boards/` - hardware: `elecrow-p4.yaml` for every size, plus
  `elecrow-p4-10in.yaml` on a 10.1"
- `partitions_16mb.csv` - two 5 MiB firmware slots, the asset area
  (downloaded theme and wording), settings and a crash report area; frozen -
  a panel moving to this layout needs one USB flash (erase the flash first)

Building from this repo: `tools/sync-firmware.sh` copies this folder into an
ESPHome config folder (`<config>/room_tiles/`), where a device file includes
the packages.
