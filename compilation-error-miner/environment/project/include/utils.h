#ifndef UTILS_H
#define UTILS_H

#include "types.h"

namespace util {

std::string bytes_to_hex(const ByteBuffer& data);
ByteBuffer hex_to_bytes(const std::string& hex);
uint32_t crc32(const uint8_t* data, size_t len);

template<typename T>
T clamp(T value, T min_val, T max_val) {
    return std::max(min_val, std::min(value, max_val));
}

} // namespace util

#endif // UTILS_H
