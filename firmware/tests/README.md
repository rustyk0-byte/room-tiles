# Firmware tests that build on a PC

`map_draw_test.cpp` draws maps with the panel's own map drawing
(`components/room_tiles/map_draw.cpp`, `raster.cpp` - no LVGL, no ESPHome)
tile by tile, as the panel does, into PPM pictures, and prints the time per
tile. It needs `test_maps.h` (a map exported to C++); a synthetic 3000-wall map
checks the spatial index.

    g++ -O2 -std=gnu++20 -I../components/room_tiles -I. map_draw_test.cpp \
        ../components/room_tiles/map_draw.cpp ../components/room_tiles/raster.cpp

`screen_policy_test.cpp` plays a panel's day against the screen's rules
(`components/room_tiles/screen_policy.cpp`: lit, dimmed, the idle clock or
dark) - touches, the room's lights, Home Assistant going and coming back,
updates, the backlight switched in HA - and checks what the screen shows.
GitHub runs it with every change to the panel's code
(`.github/workflows/firmware-tests.yml`).

    g++ -std=gnu++20 -Wall -Werror -I../components/room_tiles -o screen_policy_test \
        screen_policy_test.cpp ../components/room_tiles/screen_policy.cpp && ./screen_policy_test
