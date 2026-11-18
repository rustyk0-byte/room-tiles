# The Wi-Fi chip's firmware

The Elecrow ESP32-P4 boards get Wi-Fi from an ESP32-C6 running Espressif's
ESP-Hosted `network_adapter`, which has to match the ESP-Hosted library in the
panel firmware. Boards ship with older versions; the panel firmware carries
this image and brings the chip up to it (docs/DESIGN.md "The Wi-Fi chip").

| File | Version | SHA-256 | Source |
|---|---|---|---|
| `network_adapter_esp32c6-2.12.13.bin` | 2.12.13 | `09e4ed4ff648444ad045c1d934825af407648f58898586ce9f4275e53fdb23f6` | ESPHome's builds, https://esphome.github.io/esp-hosted-firmware/v2.12.13/network_adapter_esp32c6.bin |

ESPHome 2026.10.2 (`ESPHOME_VERSION` in .github/workflows/firmware.yml)
uses ESP-Hosted 2.12.13 on the panel side. The panel only updates a chip
when this image is exactly that library's version, so a mismatch is never
installed (it logs and leaves the chip alone). When ESPHome moves to another
ESP-Hosted version, replace the image (same source, the
matching version), its `path` and `sha256` in `firmware/boards/elecrow-p4.yaml`,
and this table.

ESP-Hosted is Espressif's, under the Apache License 2.0
(https://github.com/espressif/esp-hosted-mcu).
