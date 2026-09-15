#pragma once
#include <cstdint>

struct Tick {
    uint64_t timestamp;
    uint32_t source_id;
    double price;
    double quantity;
};
