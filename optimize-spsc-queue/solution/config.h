#pragma once

#include <cstddef>
#include <cstdint>

namespace spsc {

constexpr size_t kCacheLineSize = 64;
constexpr size_t kDefaultQueueCapacity = 1 << 20;  // 1 MB
constexpr size_t kReservationSize = 65536;          // 64 KB write reservation chunk
constexpr uint32_t kProtocolMagic = 0x53505343;     // "SPSC"
constexpr uint16_t kMajorVersion = 1;
constexpr uint16_t kMinorVersion = 0;

}  // namespace spsc
