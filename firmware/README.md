# Room Tiles panel firmware

ESPHome firmware for the Room Tiles ESP32 panels: Elecrow CrowPanel Advanced
ESP32-P4 (7", 9", 10.1" - all 1024x600) and the CrowPanel 2.1" round ESP32-S3
(480x480). Most people never build it: the install page flashes a panel, and
Room Tiles updates it after that (docs/DESIGN.md "Panel firmware").

- `room_tiles.yaml` - the panel (one firmware for every board)
- `devices/` - one file per board, named by what's printed on it; each is a
  generic image (no panel's or home's details inside)
- `identity/` - `generic.yaml` for those images, `own.yaml` for a hand-built
  panel with its own name, key and Wi-Fi
- `boards/` - hardware: `elecrow-p4.yaml` for every P4 size (plus
  `elecrow-p4-10in.yaml` on a 10.1"), `elecrow-s3-round-2.1.yaml` for the
  round panel
- `components/` - the Room Tiles C++ component, and a copy of ESPHome's
  `mipi_dsi` with one change (no blue flash while flash is written)
- `partitions_16mb.csv` (P4) and `partitions_s3_16mb.csv` (round) - two
  firmware slots, the asset area (downloaded theme and wording), settings and
  a crash report area; frozen - a panel moving to another layout needs one
  USB flash (erase the flash first)
- `wifi_chip/` - the P4 boards' Wi-Fi chip firmware, brought up to date once
  at startup
- `tests/` - plain C++ tests of the panel's logic (no hardware needed)

Building from this repo: `tools/sync-firmware.sh` copies this folder into an
ESPHome config folder (`<config>/room_tiles/`), where a device file includes
the packages.
