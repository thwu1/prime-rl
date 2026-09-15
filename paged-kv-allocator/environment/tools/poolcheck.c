/*
 * poolcheck.c — Block pool invariant checker for KV cache allocator.
 *
 * Reads a results JSON file and optionally a config JSON file,
 * then validates mathematical invariants that must hold for any
 * correct block allocator execution.
 *
 * Build: make -C /app/tools
 * Usage: /app/tools/poolcheck /app/results.json [--config /app/config.json]
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static long get_json_long(const char *json, const char *key) {
    char pattern[256];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *p = strstr(json, pattern);
    if (!p) {
        fprintf(stderr, "ERROR: key '%s' not found in JSON\n", key);
        exit(2);
    }
    p += strlen(pattern);
    while (*p == ' ' || *p == '\t' || *p == ':') p++;
    return atol(p);
}

static char *read_file(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc(len + 1);
    if (!buf) { perror("malloc"); exit(2); }
    if (fread(buf, 1, len, f) != (size_t)len) {
        perror("fread");
        free(buf);
        fclose(f);
        exit(2);
    }
    buf[len] = '\0';
    fclose(f);
    return buf;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr,
                "Usage: %s <results.json> [--config <config.json>]\n",
                argv[0]);
        return 1;
    }

    char *json = read_file(argv[1]);

    long per_token   = get_json_long(json, "per_token_kv_bytes");
    long total_alloc = get_json_long(json, "total_blocks_allocated");
    long cow         = get_json_long(json, "total_cow_copies");
    long peak        = get_json_long(json, "peak_blocks_used");
    long final_used  = get_json_long(json, "final_blocks_used");
    long wasted      = get_json_long(json, "wasted_slots_at_peak");
    long hits        = get_json_long(json, "prefix_cache_hits");
    long misses      = get_json_long(json, "prefix_cache_misses");
    long evictions   = get_json_long(json, "evictions_performed");

    int errors = 0;

    printf("=== Block Pool Invariant Check ===\n\n");

    /* Invariant 1: peak >= final */
    if (peak < final_used) {
        printf("FAIL [inv-1]: peak_blocks_used (%ld) < "
               "final_blocks_used (%ld)\n", peak, final_used);
        errors++;
    } else {
        printf("PASS [inv-1]: peak_blocks_used >= final_blocks_used\n");
    }

    /* Invariant 2: total_alloc >= peak */
    if (total_alloc < peak) {
        printf("FAIL [inv-2]: total_blocks_allocated (%ld) < "
               "peak_blocks_used (%ld)\n", total_alloc, peak);
        errors++;
    } else {
        printf("PASS [inv-2]: total_blocks_allocated >= peak_blocks_used\n");
    }

    /* Invariant 3: all non-negative */
    if (wasted < 0 || cow < 0 || hits < 0 || misses < 0 || evictions < 0) {
        printf("FAIL [inv-3]: one or more metrics are negative\n");
        errors++;
    } else {
        printf("PASS [inv-3]: all metrics non-negative\n");
    }

    /* Invariant 4: per_token > 0 */
    if (per_token <= 0) {
        printf("FAIL [inv-4]: per_token_kv_bytes (%ld) <= 0\n", per_token);
        errors++;
    } else {
        printf("PASS [inv-4]: per_token_kv_bytes > 0 (%ld)\n", per_token);
    }

    /* Invariant 5: final_used >= 0 */
    if (final_used < 0) {
        printf("FAIL [inv-5]: final_blocks_used (%ld) < 0\n", final_used);
        errors++;
    } else {
        printf("PASS [inv-5]: final_blocks_used >= 0\n");
    }

    /* Invariant 6: evictions <= total cache misses (can't evict what
       was never cached) */
    if (evictions > misses) {
        printf("FAIL [inv-6]: evictions_performed (%ld) > "
               "prefix_cache_misses (%ld)\n", evictions, misses);
        errors++;
    } else {
        printf("PASS [inv-6]: evictions_performed <= prefix_cache_misses\n");
    }

    /* Invariant 7: total_alloc >= cow (every CoW is also an allocation) */
    if (total_alloc < cow) {
        printf("FAIL [inv-7]: total_blocks_allocated (%ld) < "
               "total_cow_copies (%ld)\n", total_alloc, cow);
        errors++;
    } else {
        printf("PASS [inv-7]: total_blocks_allocated >= total_cow_copies\n");
    }

    /* Config-dependent invariants */
    if (argc >= 4 && strcmp(argv[2], "--config") == 0) {
        char *cjson = read_file(argv[3]);
        long block_size   = get_json_long(cjson, "block_size");
        long num_blocks   = get_json_long(cjson, "num_gpu_blocks");

        /* Invariant 8: wasted <= peak * block_size */
        if (wasted > peak * block_size) {
            printf("FAIL [inv-8]: wasted_slots_at_peak (%ld) > "
                   "peak * block_size (%ld)\n", wasted, peak * block_size);
            errors++;
        } else {
            printf("PASS [inv-8]: wasted_slots_at_peak <= "
                   "peak * block_size\n");
        }

        /* Invariant 9: peak <= num_gpu_blocks */
        if (peak > num_blocks) {
            printf("FAIL [inv-9]: peak_blocks_used (%ld) > "
                   "num_gpu_blocks (%ld)\n", peak, num_blocks);
            errors++;
        } else {
            printf("PASS [inv-9]: peak_blocks_used <= num_gpu_blocks\n");
        }

        free(cjson);
    }

    printf("\n%d invariant(s) violated.\n", errors);

    free(json);
    return errors > 0 ? 1 : 0;
}
