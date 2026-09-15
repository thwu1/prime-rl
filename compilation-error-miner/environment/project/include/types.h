#ifndef TYPES_H
#define TYPES_H

#include <cstdint>
#include <string>
#include <vector>

using ByteBuffer = std::vector<uint8_t>;
using ConnectionId = uint64_t;

enum class ErrorCode : int {
    OK = 0,
    TIMEOUT = 1,
    INVALID_INPUT = 2,
    CONNECTION_FAILED = 3
};

struct NetManager {
    int id;
};

class NetworkManager;  // forward declaration

struct PacketHeader {
    uint32_t magic;
    uint32_t length;
    uint16_t type;
    uint16_t flags;
};

#endif // TYPES_H
