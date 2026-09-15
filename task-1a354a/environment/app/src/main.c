/*
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "simulator.h"

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr,
            "Usage: %s <trace_file> [num_procs] [num_sets] [assoc] [block_size]\n",
            argv[0]);
        return 1;
    }

    const char *trace_file = argv[1];
    int num_procs    = argc > 2 ? atoi(argv[2]) : 4;
    int num_sets     = argc > 3 ? atoi(argv[3]) : 4;
    int associativity = argc > 4 ? atoi(argv[4]) : 2;
    int block_size   = argc > 5 ? atoi(argv[5]) : 64;

    Simulator sim;
    simulator_init(&sim, num_procs, num_sets, associativity, block_size);

    FILE *fp = fopen(trace_file, "r");
    if (!fp) {
        fprintf(stderr, "Error: cannot open '%s'\n", trace_file);
        simulator_free(&sim);
        return 1;
    }

    char line[256];
    while (fgets(line, sizeof(line), fp)) {
        /* skip comments and blank lines */
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r')
            continue;

        int proc_id;
        char op;
        uint64_t addr;
        if (sscanf(line, "%d %c %lx", &proc_id, &op, &addr) != 3)
            continue;

        if (proc_id < 0 || proc_id >= num_procs) {
            fprintf(stderr, "Error: proc %d out of range [0,%d)\n",
                    proc_id, num_procs);
            fclose(fp);
            simulator_free(&sim);
            return 1;
        }
        if (op != 'R' && op != 'W') {
            fprintf(stderr, "Error: unknown op '%c'\n", op);
            fclose(fp);
            simulator_free(&sim);
            return 1;
        }

        process_access(&sim, proc_id, op, addr);
    }

    fclose(fp);
    simulator_print_stats(&sim);
    simulator_free(&sim);
    return 0;
}
