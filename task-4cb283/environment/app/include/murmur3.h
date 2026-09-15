#ifndef MURMUR3_H
#define MURMUR3_H

#include <stdint.h>
#include <stddef.h>

uint32_t murmur3_32(const uint8_t *key, size_t len, uint32_t seed);

#endif /* MURMUR3_H */
