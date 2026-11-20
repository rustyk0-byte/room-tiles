#include "signing.h"

#include <cstdio>
#include <ctime>

#include <mbedtls/md.h>
#include <mbedtls/sha256.h>

#include "esphome/components/api/api_server.h"
#include "esphome/core/application.h"

namespace esphome::room_tiles {

// the clock counts as set (from HA's time) after this (2023-11-14)
static const time_t TIME_VALID = 1700000000;

static void hex(const uint8_t *in, size_t n, char *out) {
  for (size_t i = 0; i < n; i++)
    snprintf(out + i * 2, 3, "%02x", in[i]);
}

bool has_api_key() {
#ifdef USE_API_NOISE
  if (api::global_api_server == nullptr)
    return false;
  noise::psk_t key;
  api::global_api_server->get_noise_ctx().load_psk(key);
  return !noise::NoiseContext::is_all_zeros(key);
#else
  return false;
#endif
}

SignResult sign_request(const char *method, const char *path, const std::string &params, const uint8_t *body,
                        size_t size, std::string &query) {
  const time_t now = ::time(nullptr);
  if (now < TIME_VALID)
    return SignResult::NO_TIME;
#ifdef USE_API_NOISE
  noise::psk_t key;
  api::global_api_server->get_noise_ctx().load_psk(key);
  if (noise::NoiseContext::is_all_zeros(key))
    return SignResult::NO_KEY;
  const std::string node = App.get_name().str();
  const std::string unsigned_query =
      "name=" + node + "&ts=" + std::to_string((long long) now) + "&schema=" + std::to_string(PANEL_SCHEMA) + params;
  std::string msg = std::string("RT2\n") + method + "\n" + path + "\n" + unsigned_query + "\n";
  if (body != nullptr) {
    uint8_t digest[32];
    char digest_hex[65];
    mbedtls_sha256(body, size, digest, 0);
    hex(digest, 32, digest_hex);
    msg += digest_hex;
  }
  uint8_t mac[32];
  if (mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key.data(), key.size(),
                      reinterpret_cast<const unsigned char *>(msg.data()), msg.size(), mac) != 0)
    return SignResult::NO_KEY;
  char sig[65];
  hex(mac, 32, sig);
  query = "?" + unsigned_query + "&sig=" + sig;
  return SignResult::OK;
#else
  return SignResult::NO_KEY;
#endif
}

}  // namespace esphome::room_tiles
