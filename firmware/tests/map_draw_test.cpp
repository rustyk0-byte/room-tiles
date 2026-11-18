#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <chrono>
#include "map_draw.h"
#include "test_maps.h"
using namespace esphome::room_tiles;
// render the view (vw x vh) of map m at zoom z centred, by 256 px tiles, write PPM
static void render(const MapSpec &m, float z, int vw, int vh, const char *path) {
  const float bw = m.bounds[2] - m.bounds[0], bh = m.bounds[3] - m.bounds[1];
  const float k1 = std::min(vw / bw, vh / bh);  // zoom 1: the whole map fits
  const float k = k1 * z;
  const float cx = bw * k / 2, cy = bh * k / 2;  // the camera at the middle
  const int vx0 = (int) floorf(cx - vw / 2.0f), vy0 = (int) floorf(cy - vh / 2.0f);
  std::vector<uint16_t> view(vw * vh), tile(256 * 256);
  const int tx0 = (int) floorf(vx0 / 256.0f), ty0 = (int) floorf(vy0 / 256.0f);
  const int tx1 = (int) floorf((vx0 + vw - 1) / 256.0f), ty1 = (int) floorf((vy0 + vh - 1) / 256.0f);
  MapColors c;
  MapIndex index(m);
  auto t0 = std::chrono::steady_clock::now();
  int tiles = 0;
  for (int ty = ty0; ty <= ty1; ty++)
    for (int tx = tx0; tx <= tx1; tx++) {
      draw_map_tile(m, index, c, k, tx * 256, ty * 256, tile.data(), 256);
      tiles++;
      for (int y = 0; y < 256; y++)
        for (int x = 0; x < 256; x++) {
          int X = tx * 256 + x - vx0, Y = ty * 256 + y - vy0;
          if (X >= 0 && Y >= 0 && X < vw && Y < vh) view[Y * vw + X] = tile[y * 256 + x];
        }
    }
  auto ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  printf("%s zoom %.2f: %d tiles in %.1f ms (%.2f ms/tile, PC)\n", m.id.c_str(), z, tiles, ms, ms / tiles);
  FILE *f = fopen(path, "wb");
  fprintf(f, "P6 %d %d 255\n", vw, vh);
  for (uint16_t p : view) {
    unsigned char rgb[3] = {(unsigned char) (((p >> 11) & 31) * 255 / 31), (unsigned char) (((p >> 5) & 63) * 255 / 63), (unsigned char) ((p & 31) * 255 / 31)};
    fwrite(rgb, 1, 3, f);
  }
  fclose(f);
}
int main() {
  auto maps = test_maps();
  // a synthetic big map: 3000 walls in a 60 x 25 grid of rooms
  MapSpec big = maps[0];
  big.walls.clear();
  big.bounds[0] = 0; big.bounds[1] = 0; big.bounds[2] = 6000; big.bounds[3] = 2500;
  for (int i = 0; i <= 60; i++) big.walls.push_back({i * 100.0f, 0, i * 100.0f, 2500});
  for (int j = 0; j <= 25; j++) for (int i = 0; i < 60; i++) big.walls.push_back({i * 100.0f, j * 100.0f, i * 100.0f + 100, j * 100.0f});
  for (int j = 0; j < 25; j++) for (int i = 0; i < 60; i++) big.walls.push_back({i * 100.0f + 50, j * 100.0f, i * 100.0f + 50, j * 100.0f + 40});
  printf("big map: %zu walls\n", big.walls.size());
  render(big, 1.0f, 1024, 552, "big_z1.ppm");
  render(big, 8.0f, 1024, 552, "big_z8.ppm");
  render(maps[0], 1.0f, 1024, 552, "house_z1.ppm");
  render(maps[0], 3.0f, 1024, 552, "house_z3.ppm");
  render(maps[1], 1.0f, 1024, 552, "outside_z1.ppm");
  return 0;
}
