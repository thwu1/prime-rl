 *
 * Native address computation routines for the MOESI cache coherence
 * simulator's banked L2 cache.  Called from Python via ctypes.
 */

#include <stdint.h>

/*
 * Compute the interleave mask used for bank selection.
 * Given intlv_bits (log2 of the number of banks), produce a
 * bitmask that isolates those bits from an address field.
 */
uint32_t get_intlv_mask(uint32_t intlv_bits) {
    return (1u << intlv_bits);
}

/*
 * Determine which bank an address maps to.
 * Extracts intlv_bits worth of bits starting at intlv_low_bit
 * position and maps to a bank index in [0, num_banks).
 */
uint32_t compute_bank_index(uint64_t addr, uint32_t intlv_low_bit,
                            uint32_t intlv_mask, uint32_t num_banks) {
    uint32_t raw = (uint32_t)((addr >> intlv_low_bit) & intlv_mask);
    return raw % num_banks;
}

/*
 * Compute the cache set index within a single bank.
 * Extracts set index bits starting at bit position shift_bits
 * in the address, masked by set_mask.
 */
uint32_t compute_set_index(uint64_t addr, uint32_t set_mask,
                           uint32_t shift_bits) {
    return (uint32_t)((addr >> shift_bits) & set_mask);
}
