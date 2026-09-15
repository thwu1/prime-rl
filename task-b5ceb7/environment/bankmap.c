/*
 * bankmap - Shared memory bank conflict mapping visualizer
 *
 * Compiled via Makefile which generates config.h from gpu_config.json.
 * NUM_BANKS, BANK_WIDTH, WARP_SIZE are injected at compile time.
 *
 * Usage: ./bankmap addr0 addr1 ... addr31
 *   Provide byte addresses for each thread in a warp.
 *   Outputs per-thread bank assignments and conflict summary.
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* NUM_BANKS, BANK_WIDTH, WARP_SIZE defined via -include config.h */

int compute_bank(int addr) {
    return (addr / BANK_WIDTH) % NUM_BANKS;
}

int main(int argc, char *argv[]) {
    printf("Bank configuration: NUM_BANKS=%d, BANK_WIDTH=%d, WARP_SIZE=%d\n\n",
           NUM_BANKS, BANK_WIDTH, WARP_SIZE);

    if (argc < 2) {
        fprintf(stderr, "Usage: %s addr0 addr1 ... addr31\n", argv[0]);
        fprintf(stderr, "  Provide %d byte addresses (one per warp thread)\n", WARP_SIZE);
        return 1;
    }

    int n = argc - 1;
    if (n > WARP_SIZE) n = WARP_SIZE;

    int addrs[32];
    for (int i = 0; i < n; i++)
        addrs[i] = atoi(argv[i + 1]);

    /* Track distinct addresses per bank (broadcast deduplication) */
    int bank_addr_list[256][32];
    int bank_addr_count[256];
    memset(bank_addr_count, 0, sizeof(bank_addr_count));

    printf("Thread  ByteAddr  Bank\n");
    printf("------  --------  ----\n");

    for (int i = 0; i < n; i++) {
        int bank = compute_bank(addrs[i]);
        printf("  t%-2d    %6d    %2d\n", i, addrs[i], bank);

        /* Deduplicate: only count each distinct address once per bank */
        int is_dup = 0;
        for (int j = 0; j < bank_addr_count[bank]; j++) {
            if (bank_addr_list[bank][j] == addrs[i]) {
                is_dup = 1;
                break;
            }
        }
        if (!is_dup && bank_addr_count[bank] < 32) {
            bank_addr_list[bank][bank_addr_count[bank]++] = addrs[i];
        }
    }

    int max_wf = 0, total_conf = 0;
    printf("\nBank  Distinct  Conflicts\n");
    printf("----  --------  ---------\n");
    for (int b = 0; b < NUM_BANKS; b++) {
        int d = bank_addr_count[b];
        if (d > 0) {
            int c = d > 1 ? d - 1 : 0;
            printf("  %2d       %2d        %2d\n", b, d, c);
            if (d > max_wf) max_wf = d;
            total_conf += c;
        }
    }
    if (max_wf == 0 && n > 0) max_wf = 1;

    printf("\nSummary: wavefronts=%d  total_conflicts=%d  conflict_free=%s\n",
           max_wf, total_conf, total_conf == 0 ? "true" : "false");

    return 0;
}
