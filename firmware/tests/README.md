# Firmware tests that build on a PC

`map_draw_test.cpp` draws maps with the panel's own map drawing
(`components/room_tiles/map_draw.cpp`, `raster.cpp` - no LVGL, no ESPHome)
tile by tile, as the panel does, into PPM pictures, and prints the time per
tile. It needs `test_maps.h` (a map exported to C++); a synthetic 3000-wall map
checks the spatial index.

    g++ -O2 -std=gnu++20 -I../components/room_tiles -I. map_draw_test.cpp \
        ../components/room_tiles/map_draw.cpp ../components/room_tiles/raster.cpp
