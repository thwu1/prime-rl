/*
 * Systolic Array Cycle-Accurate Simulator
 *
 * Models cycle cost of tiled matrix multiplication C[M,N] = A[M,K]*B[K,N]+D[M,N]
 * on a DIM x DIM systolic array with double-buffered scratchpad and accumulator.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int ceildiv(int a, int b) {
    return (a + b - 1) / b;
}

static long long evaluate(int DIM, int SP_ROWS, int ACC_ROWS, int DMA_COST,
                          int DMA_SETUP, int M, int N, int K,
                          int i_tile, int j_tile, int k_tile) {
    int sp_budget, acc_budget;
    int I_outer, J_outer, K_outer;
    int PD, CO;
    long long total;
    int io, jo, ko;

    if (i_tile < 1 || j_tile < 1 || k_tile < 1) return -1;

    sp_budget = SP_ROWS / 2;
    acc_budget = ACC_ROWS / 2;

    if (i_tile * k_tile + k_tile * j_tile > sp_budget) return -1;
    if (i_tile * j_tile > acc_budget) return -1;

    I_outer = ceildiv(M, i_tile * DIM);
    J_outer = ceildiv(N, j_tile * DIM);
    K_outer = ceildiv(K, k_tile * DIM);

    PD = DIM - 1;
    CO = 16;
    total = 0;

    for (io = 0; io < I_outer; io++) {
        int eff_m = i_tile * DIM;
        int rem_m = M - io * i_tile * DIM;
        int eff_i;
        if (rem_m < eff_m) eff_m = rem_m;
        eff_i = ceildiv(eff_m, DIM);

        for (jo = 0; jo < J_outer; jo++) {
            int eff_n = j_tile * DIM;
            int rem_n = N - jo * j_tile * DIM;
            int eff_j;
            long long ij_cyc;
            if (rem_n < eff_n) eff_n = rem_n;
            eff_j = ceildiv(eff_n, DIM);

            ij_cyc = CO;

            for (ko = 0; ko < K_outer; ko++) {
                int eff_kd = k_tile * DIM;
                int rem_k = K - ko * k_tile * DIM;
                int eff_k;
                long long la, lb, tl, comp;
                if (rem_k < eff_kd) eff_kd = rem_k;
                eff_k = ceildiv(eff_kd, DIM);

                la = (long long)eff_i * eff_k * DMA_COST + DMA_SETUP;
                lb = (long long)eff_k * eff_j * DMA_COST + DMA_SETUP;
                tl = la + lb;

                if (ko == 0) {
                    tl += (long long)eff_i * eff_j * DMA_COST + DMA_SETUP;
                }

                comp = (long long)eff_i * eff_j * eff_k * DIM;

                if (ko == 0) {
                    ij_cyc += tl + comp;
                } else {
                    ij_cyc += (tl > comp) ? tl : comp;
                }
            }

            ij_cyc += PD;
            ij_cyc += (long long)eff_i * eff_j * DMA_COST + DMA_SETUP;

            total += ij_cyc;
        }
    }

    return total;
}

static void print_help(const char *prog) {
    printf("Systolic Array Cycle-Accurate Simulator\n\n");
    printf("Models the cycle cost of tiled matrix multiplication\n");
    printf("C[M,N] = A[M,K]*B[K,N]+D[M,N] on a DIM x DIM systolic array\n");
    printf("with double-buffered scratchpad and accumulator memories.\n\n");
    printf("SINGLE EVALUATION:\n");
    printf("  %s <dim> <sp_rows> <acc_rows> <dma_cost> <dma_setup>", prog);
    printf(" <M> <N> <K> <i_tile> <j_tile> <k_tile>\n");
    printf("  Prints integer cycle count to stdout.\n");
    printf("  Prints -1 if tiling violates memory constraints.\n\n");
    printf("BATCH MODE:\n");
    printf("  %s --batch <dim> <sp_rows> <acc_rows> <dma_cost> <dma_setup>\n", prog);
    printf("  Reads lines of 'M N K i_tile j_tile k_tile' from stdin.\n");
    printf("  Outputs one integer cycle count per line to stdout.\n");
    printf("  Terminate input with EOF.\n\n");
    printf("CONSTRAINT CHECK:\n");
    printf("  %s --check <sp_rows> <acc_rows> <i_tile> <j_tile> <k_tile>\n", prog);
    printf("  Prints 'valid' or 'invalid' for the given tiling.\n\n");
    printf("MEMORY MODEL:\n");
    printf("  Scratchpad budget = sp_rows / 2  (double-buffered)\n");
    printf("  Accumulator budget = acc_rows / 2  (double-buffered)\n");
    printf("  Scratchpad usage = i_tile * k_tile + k_tile * j_tile\n");
    printf("  Accumulator usage = i_tile * j_tile\n\n");
    printf("EXECUTION MODEL:\n");
    printf("  - Config overhead: 16 cycles per (i,j) outer tile group\n");
    printf("  - First K iteration: cold start, loads fully serialized\n");
    printf("  - Subsequent K iters: loads overlap compute (double-buffering)\n");
    printf("  - Pipeline drain: DIM-1 cycles after last compute per group\n");
    printf("  - DMA cost: rows * dma_cost + dma_setup per transaction\n");
    printf("  - Transactions: load_A, load_B, load_D (first K only), store_C\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Error: no arguments. Use --help for usage.\n");
        return 1;
    }

    if (strcmp(argv[1], "-h") == 0 || strcmp(argv[1], "--help") == 0) {
        print_help(argv[0]);
        return 0;
    }

    if (strcmp(argv[1], "--batch") == 0) {
        int dim, sp, acc, dma, dmas;
        int M, N, K, i, j, k;
        if (argc != 7) {
            fprintf(stderr,
                "Batch: --batch <dim> <sp_rows> <acc_rows> <dma_cost> <dma_setup>\n");
            return 1;
        }
        dim = atoi(argv[2]);
        sp = atoi(argv[3]);
        acc = atoi(argv[4]);
        dma = atoi(argv[5]);
        dmas = atoi(argv[6]);

        while (scanf("%d %d %d %d %d %d", &M, &N, &K, &i, &j, &k) == 6) {
            printf("%lld\n", evaluate(dim, sp, acc, dma, dmas, M, N, K, i, j, k));
            fflush(stdout);
        }
        return 0;
    }

    if (strcmp(argv[1], "--check") == 0) {
        int sp_budget, acc_budget, i, j, k;
        if (argc != 7) {
            fprintf(stderr,
                "Check: --check <sp_rows> <acc_rows> <i_tile> <j_tile> <k_tile>\n");
            return 1;
        }
        sp_budget = atoi(argv[2]) / 2;
        acc_budget = atoi(argv[3]) / 2;
        i = atoi(argv[4]);
        j = atoi(argv[5]);
        k = atoi(argv[6]);
        if (i >= 1 && j >= 1 && k >= 1 &&
            i * k + k * j <= sp_budget && i * j <= acc_budget)
            printf("valid\n");
        else
            printf("invalid\n");
        return 0;
    }

    if (argc == 12) {
        printf("%lld\n", evaluate(
            atoi(argv[1]), atoi(argv[2]), atoi(argv[3]),
            atoi(argv[4]), atoi(argv[5]), atoi(argv[6]),
            atoi(argv[7]), atoi(argv[8]), atoi(argv[9]),
            atoi(argv[10]), atoi(argv[11])));
        return 0;
    }

    fprintf(stderr, "Invalid arguments. Use --help for usage information.\n");
    return 1;
}
