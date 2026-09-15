#ifndef BITPOOL_H
#define BITPOOL_H

#include <stdint.h>

typedef struct bitpool_t bitpool_t;

bitpool_t *bitpool_create(uint64_t seed);
void bitpool_free(bitpool_t *pool);
int bitpool_get_bit(bitpool_t *pool);
int bitpool_bits_used(bitpool_t *pool);
void bitpool_reset(bitpool_t *pool, uint64_t seed);

#endif
