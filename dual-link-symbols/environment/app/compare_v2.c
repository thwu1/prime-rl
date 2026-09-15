#include <stdint.h>
#include <stddef.h>
#include "checksum.h"

void run_v2(const uint8_t *data, size_t len, uint32_t results[8]) {
    results[0] = checksum_adler32(data, len);
    results[1] = checksum_crc32(data, len);
    results[2] = checksum_djb2(data, len);
    results[3] = checksum_fletcher16(data, len);
    results[4] = checksum_fnv1a(data, len);
    results[5] = checksum_rotxor(data, len);
    results[6] = checksum_sdbm(data, len);
    results[7] = checksum_xor8(data, len);
}
