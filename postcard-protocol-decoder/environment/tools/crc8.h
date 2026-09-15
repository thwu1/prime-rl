/*
 * CRC-8 with polynomial 0x31 (x^8 + x^5 + x^4 + 1)
 * Init: 0x00, no reflection, no final XOR
 */

#ifndef CRC8_H
#define CRC8_H

#include <stdint.h>
#include <stddef.h>

uint8_t crc8_compute(const uint8_t *data, size_t len);

#endif /* CRC8_H */
