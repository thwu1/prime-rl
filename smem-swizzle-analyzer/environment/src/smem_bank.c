
#include "smem_bank.h"

int compute_bank_id(int byte_address) {
    return (byte_address / BANK_WIDTH_BYTES) % NUM_BANKS;
}

int count_bank_conflicts(const int *byte_addresses, size_t count) {
    if (count == 0) return 0;

    int bank_counts[NUM_BANKS];
    for (int i = 0; i < NUM_BANKS; i++) bank_counts[i] = 0;

    for (size_t i = 0; i < count; i++) {
        int bank = compute_bank_id(byte_addresses[i]);
        bank_counts[bank]++;
    }

    /* Compute aggregate serialization penalty across all banks. */
    int total = 0;
    for (int b = 0; b < NUM_BANKS; b++) {
        if (bank_counts[b] > 1) {
            total += bank_counts[b] - 1;
        }
    }
    return total > 0 ? total : 1;
}
