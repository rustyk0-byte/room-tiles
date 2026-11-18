ESPHome 2026.10.2's `mipi_dsi` display component, unchanged except for one
line: its refresh callback is marked `IRAM_ATTR`.

Why: with ESP-IDF's `CONFIG_LCD_DSI_ISR_CACHE_SAFE` the display's next frame
is started even while flash is being written (a language or theme pack, an
update) - without it the screen flashes blue then. ESP-IDF only accepts that
option when the driver's callbacks are in IRAM; ESPHome's isn't yet.

Drop this folder once ESPHome ships the callback in IRAM.

License: like ESPHome's C++ code, this folder is under the GNU General
Public License v3 (https://www.gnu.org/licenses/gpl-3.0.html) - not the
Apache License the rest of Room Tiles uses (NOTICE).
