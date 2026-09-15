#define _GNU_SOURCE
#include "dispatch.h"
#include "handlers.h"
#include <stdio.h>
#include <string.h>
#include <time.h>

/* ================================================================
 * Statistics tracking
 *
 * TODO: This entire section should be in its own translation unit
 * (stats.c / stats.h). It is embedded here for historical reasons.
 * ================================================================ */

static struct {
    int initialized;
    int error_counts[CMD_TYPE_COUNT];
    double total_latency[CMD_TYPE_COUNT];
    int op_counts[CMD_TYPE_COUNT];
    int throughput_samples[64];
    int throughput_idx;
    int throughput_count;
} g_stats;

void stats_init(void) {
    memset(&g_stats, 0, sizeof(g_stats));
    g_stats.initialized = 1;
}

void stats_cleanup(void) {
    memset(&g_stats, 0, sizeof(g_stats));
}

void stats_record_latency(cmd_type_t type, double ms) {
    if (!g_stats.initialized || type < 0 || type >= CMD_TYPE_COUNT)
        return;
    g_stats.total_latency[type] += ms;
    g_stats.op_counts[type]++;
}

void stats_record_throughput(int ops_per_sec) {
    if (!g_stats.initialized)
        return;
    g_stats.throughput_samples[g_stats.throughput_idx % 64] = ops_per_sec;
    g_stats.throughput_idx++;
    if (g_stats.throughput_count < 64)
        g_stats.throughput_count++;
}

void stats_record_error(cmd_type_t type, int error_code) {
    if (!g_stats.initialized || type < 0 || type >= CMD_TYPE_COUNT)
        return;
    g_stats.error_counts[type]++;
    (void)error_code;
}

int stats_get_total_errors(void) {
    int total = 0;
    for (int i = 0; i < CMD_TYPE_COUNT; i++)
        total += g_stats.error_counts[i];
    return total;
}

int stats_get_type_errors(cmd_type_t type) {
    if (type < 0 || type >= CMD_TYPE_COUNT)
        return 0;
    return g_stats.error_counts[type];
}

void stats_report(char *buf, size_t buflen) {
    if (!buf || buflen == 0)
        return;
    int pos = 0;
    pos += snprintf(buf + pos, buflen - pos, "=== Statistics Report ===\n");
    for (int i = 0; i < CMD_TYPE_COUNT && pos < (int)buflen; i++) {
        double avg = g_stats.op_counts[i] > 0
            ? g_stats.total_latency[i] / g_stats.op_counts[i]
            : 0.0;
        pos += snprintf(buf + pos, buflen - pos,
                        "  %-8s: ops=%d avg_latency=%.2fms errors=%d\n",
                        cmd_type_name((cmd_type_t)i),
                        g_stats.op_counts[i], avg,
                        g_stats.error_counts[i]);
    }
    if (g_stats.throughput_count > 0 && pos < (int)buflen) {
        int sum = 0;
        for (int i = 0; i < g_stats.throughput_count; i++)
            sum += g_stats.throughput_samples[i];
        pos += snprintf(buf + pos, buflen - pos,
                        "  avg_throughput: %d ops/s\n",
                        sum / g_stats.throughput_count);
    }
}

/* ================================================================
 * Dispatch context management
 * ================================================================ */

void dispatch_ctx_init(dispatch_ctx_t *ctx, int id, const char *source,
                       CMD_MEMORY_MODE mode) {
    if (!ctx) return;
    ctx->magic = FRAMEWORK_MAGIC;
    ctx->id = id;
    ctx->source = source;
    ctx->mem_mode = mode;
    ctx->user_data = NULL;
    ctx->last_error = 0;
    ctx->error_msg[0] = '\0';
}

void dispatch_ctx_cleanup(dispatch_ctx_t *ctx) {
    if (!ctx) return;
    ctx->user_data = NULL;
    ctx->last_error = 0;
    ctx->error_msg[0] = '\0';
}

/* ================================================================
 * Command dispatch
 *
 * NOTE: dispatch_command and dispatch_pipeline both contain the same
 * handler execution pattern: save mode, set mode, reset error, call
 * handler, record timing, restore mode, check error. This pattern
 * should be consolidated into a helper function.
 * ================================================================ */

void dispatch_command(dispatch_ctx_t *ctx, cmd_type_t type,
                      const char *payload, size_t len) {
    if (!ctx) return;

    handler_func_t handler = get_handler_for_type(type);
    if (!handler) {
        ctx->last_error = -100;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "no handler for command type %d", type);
        stats_record_error(type, -100);
        return;
    }

    /* --- duplicated handler execution pattern --- */
    CMD_MEMORY_MODE saved_mode = ctx->mem_mode;
    ctx->last_error = 0;
    ctx->error_msg[0] = '\0';

    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);

    handler(ctx, payload, len);

    clock_gettime(CLOCK_MONOTONIC, &end);
    double ms = (end.tv_sec - start.tv_sec) * 1000.0 +
                (end.tv_nsec - start.tv_nsec) / 1e6;
    stats_record_latency(type, ms);

    ctx->mem_mode = saved_mode;

    if (ctx->last_error != 0) {
        stats_record_error(type, ctx->last_error);
    }
    /* --- end duplicated pattern --- */
}

/* ================================================================
 * Pipeline dispatch
 *
 * BUG: The pipeline cannot reliably stop on error because handler
 * functions return void. We check ctx->last_error after each call,
 * but this is unreliable — a handler might not clear last_error on
 * success, or a previous error might linger. The correct fix is to
 * make handlers return an int error code.
 * ================================================================ */

void dispatch_pipeline(dispatch_ctx_t *ctx, cmd_entry_t *entries, int count) {
    if (!ctx || !entries || count <= 0) return;

    for (int i = 0; i < count; i++) {
        cmd_entry_t *e = &entries[i];

        handler_func_t h = e->handler;
        if (!h) {
            h = get_handler_for_type(e->type);
            if (!h) {
                ctx->last_error = -100;
                snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                         "pipeline: no handler for entry %d (type %d)",
                         i, e->type);
                return;
            }
        }

        /* --- duplicated handler execution pattern --- */
        CMD_MEMORY_MODE saved_mode = ctx->mem_mode;
        ctx->mem_mode = e->alloc;
        ctx->last_error = 0;
        ctx->error_msg[0] = '\0';

        struct timespec start, end;
        clock_gettime(CLOCK_MONOTONIC, &start);

        h(ctx, e->name, e->name ? strlen(e->name) : 0);

        clock_gettime(CLOCK_MONOTONIC, &end);
        double ms = (end.tv_sec - start.tv_sec) * 1000.0 +
                    (end.tv_nsec - start.tv_nsec) / 1e6;
        stats_record_latency(e->type, ms);

        ctx->mem_mode = saved_mode;

        if (ctx->last_error != 0) {
            stats_record_error(e->type, ctx->last_error);
            /* Pipeline continues despite error — this is the bug.
             * We cannot reliably stop because handlers return void
             * and last_error is fragile. */
        }
        /* --- end duplicated pattern --- */
    }
}
