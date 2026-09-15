#ifndef CHECKSUM_H
#define CHECKSUM_H

#include <stdint.h>
#include <stddef.h>

uint32_t checksum_adler32(const uint8_t *data, size_t len);
uint32_t checksum_crc32(const uint8_t *data, size_t len);
uint32_t checksum_djb2(const uint8_t *data, size_t len);
uint32_t checksum_fletcher16(const uint8_t *data, size_t len);
uint32_t checksum_fnv1a(const uint8_t *data, size_t len);
uint32_t checksum_rotxor(const uint8_t *data, size_t len);
uint32_t checksum_sdbm(const uint8_t *data, size_t len);
uint32_t checksum_xor8(const uint8_t *data, size_t len);

#endif /* CHECKSUM_H */
