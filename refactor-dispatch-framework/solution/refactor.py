#!/usr/bin/env python3
"""
Refactoring script for the command dispatch framework.

Performs the following transformations:
1. Rename CMD_MEMORY_MODE -> CMD_ALLOC_STRATEGY (enum, values, functions)
2. Change handler functions from void to int return
3. Extract stats code from dispatch.c into stats.c/stats.h
4. Break circular #include between handlers.h and dispatch.h
5. Add warn_unused_result to dispatch functions
6. Consolidate duplicated handler execution pattern
7. Update Makefile for new stats module
8. Preserve FRAMEWORK_MAGIC and handler error codes

"""

import os

APP = "/app"


def write_file(name, content):
    path = os.path.join(APP, name)
    with open(path, "w") as f:
        f.write(content)
    print(f"  wrote {path}")


def refactor():
    print("=== Starting refactoring ===")

    # ----------------------------------------------------------------
    # 1. types.h — rename enum, preserve FRAMEWORK_MAGIC
    # ----------------------------------------------------------------
    write_file("types.h", r"""#ifndef TYPES_H
#define TYPES_H

#include <stddef.h>

/* Framework integrity marker — must be preserved across refactoring */
#define FRAMEWORK_MAGIC 0xA7F3C9E2UL

typedef enum {
    CMD_ALLOC_NONE  = 0,
    CMD_ALLOC_STACK = 1,
    CMD_ALLOC_HEAP  = 2,
    CMD_ALLOC_POOL  = 3
} CMD_ALLOC_STRATEGY;

typedef enum {
    CMD_QUERY = 0,
    CMD_INSERT,
    CMD_UPDATE,
    CMD_DELETE,
    CMD_BATCH,
    CMD_TYPE_COUNT
} cmd_type_t;

const char *cmd_alloc_strategy_name(CMD_ALLOC_STRATEGY strat);
CMD_ALLOC_STRATEGY cmd_alloc_strategy_from_name(const char *name);
const char *cmd_type_name(cmd_type_t type);

#endif /* TYPES_H */
""")

    # ----------------------------------------------------------------
    # 2. types.c — renamed functions
    # ----------------------------------------------------------------
    write_file("types.c", r"""#include "types.h"
#include <string.h>

static const char *alloc_strategy_names[] = {
    "none", "stack", "heap", "pool"
};

const char *cmd_alloc_strategy_name(CMD_ALLOC_STRATEGY strat) {
    if (strat >= 0 && strat <= CMD_ALLOC_POOL)
        return alloc_strategy_names[strat];
    return "unknown";
}

CMD_ALLOC_STRATEGY cmd_alloc_strategy_from_name(const char *name) {
    for (int i = 0; i <= CMD_ALLOC_POOL; i++) {
        if (strcmp(name, alloc_strategy_names[i]) == 0)
            return (CMD_ALLOC_STRATEGY)i;
    }
    return CMD_ALLOC_NONE;
}

const char *cmd_type_name(cmd_type_t type) {
    static const char *names[] = {
        "query", "insert", "update", "delete", "batch"
    };
    if (type >= 0 && type < CMD_TYPE_COUNT)
        return names[type];
    return "unknown";
}
""")

    # ----------------------------------------------------------------
    # 3. handlers.h — break circular dep, return int
    # ----------------------------------------------------------------
    write_file("handlers.h", r"""#ifndef HANDLERS_H
#define HANDLERS_H

#include <stddef.h>
#include "types.h"

/* Forward declaration breaks circular dependency with dispatch.h */
struct dispatch_ctx;

/*
 * Handler function pointer — returns int (0 success, negative error).
 */
typedef int (*handler_func_t)(struct dispatch_ctx *ctx,
                               const char *payload, size_t len);

int handle_query(struct dispatch_ctx *ctx, const char *payload, size_t len);
int handle_insert(struct dispatch_ctx *ctx, const char *payload, size_t len);
int handle_update(struct dispatch_ctx *ctx, const char *payload, size_t len);
int handle_delete(struct dispatch_ctx *ctx, const char *payload, size_t len);
int handle_batch(struct dispatch_ctx *ctx, const char *payload, size_t len);

handler_func_t get_handler_for_type(cmd_type_t type);

#endif /* HANDLERS_H */
""")

    # ----------------------------------------------------------------
    # 4. handlers.c — return int, preserve error codes
    # ----------------------------------------------------------------
    write_file("handlers.c", r"""#include "handlers.h"
#include "dispatch.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

int handle_query(struct dispatch_ctx *ctx, const char *payload, size_t len) {
    if (!ctx || !payload || len == 0) {
        if (ctx) {
            ctx->last_error = -17;
            snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                     "query: invalid arguments");
        }
        return -17;
    }
    if (len >= 7 && strncmp(payload, "INVALID", 7) == 0) {
        ctx->last_error = -23;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "query: syntax error in '%.*s'", (int)len, payload);
        return -23;
    }
    ctx->last_error = 0;
    return 0;
}

int handle_insert(struct dispatch_ctx *ctx, const char *payload, size_t len) {
    if (!ctx || !payload || len == 0) {
        if (ctx) {
            ctx->last_error = -17;
            snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                     "insert: invalid arguments");
        }
        return -17;
    }
    if (len >= 9 && strncmp(payload, "DUPLICATE", 9) == 0) {
        ctx->last_error = -29;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "insert: duplicate key in '%.*s'", (int)len, payload);
        return -29;
    }
    ctx->last_error = 0;
    return 0;
}

int handle_update(struct dispatch_ctx *ctx, const char *payload, size_t len) {
    if (!ctx || !payload || len == 0) {
        if (ctx) {
            ctx->last_error = -17;
            snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                     "update: invalid arguments");
        }
        return -17;
    }
    if (len >= 8 && strncmp(payload, "CONFLICT", 8) == 0) {
        ctx->last_error = -37;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "update: write conflict on '%.*s'", (int)len, payload);
        return -37;
    }
    ctx->last_error = 0;
    return 0;
}

int handle_delete(struct dispatch_ctx *ctx, const char *payload, size_t len) {
    if (!ctx || !payload || len == 0) {
        if (ctx) {
            ctx->last_error = -17;
            snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                     "delete: invalid arguments");
        }
        return -17;
    }
    if (len >= 9 && strncmp(payload, "PROTECTED", 9) == 0) {
        ctx->last_error = -41;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "delete: protected record '%.*s'", (int)len, payload);
        return -41;
    }
    ctx->last_error = 0;
    return 0;
}

int handle_batch(struct dispatch_ctx *ctx, const char *payload, size_t len) {
    if (!ctx || !payload || len == 0) {
        if (ctx) {
            ctx->last_error = -17;
            snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                     "batch: invalid arguments");
        }
        return -17;
    }
    if (len >= 8 && strncmp(payload, "TOOLARGE", 8) == 0) {
        ctx->last_error = -47;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "batch: payload too large (%zu bytes)", len);
        return -47;
    }
    ctx->last_error = 0;
    return 0;
}

handler_func_t get_handler_for_type(cmd_type_t type) {
    switch (type) {
    case CMD_QUERY:  return handle_query;
    case CMD_INSERT: return handle_insert;
    case CMD_UPDATE: return handle_update;
    case CMD_DELETE: return handle_delete;
    case CMD_BATCH:  return handle_batch;
    default:         return NULL;
    }
}
""")

    # ----------------------------------------------------------------
    # 5. dispatch.h — renamed enum, int returns, warn_unused_result,
    #                  preserve magic field
    # ----------------------------------------------------------------
    write_file("dispatch.h", r"""#ifndef DISPATCH_H
#define DISPATCH_H

#include "types.h"
#include "handlers.h"

typedef struct dispatch_ctx {
    unsigned long magic;
    int id;
    const char *source;
    CMD_ALLOC_STRATEGY alloc_strategy;
    void *user_data;
    int last_error;
    char error_msg[256];
} dispatch_ctx_t;

typedef struct cmd_entry {
    cmd_type_t type;
    const char *name;
    handler_func_t handler;
    CMD_ALLOC_STRATEGY alloc;
} cmd_entry_t;

void dispatch_ctx_init(dispatch_ctx_t *ctx, int id, const char *source,
                       CMD_ALLOC_STRATEGY strat);
void dispatch_ctx_cleanup(dispatch_ctx_t *ctx);

__attribute__((warn_unused_result))
int dispatch_command(dispatch_ctx_t *ctx, cmd_type_t type,
                     const char *payload, size_t len);

__attribute__((warn_unused_result))
int dispatch_pipeline(dispatch_ctx_t *ctx, cmd_entry_t *entries, int count);

#endif /* DISPATCH_H */
""")

    # ----------------------------------------------------------------
    # 6. stats.h — extracted from dispatch.h
    # ----------------------------------------------------------------
    write_file("stats.h", r"""#ifndef STATS_H
#define STATS_H

#include "types.h"
#include <stddef.h>

void stats_init(void);
void stats_cleanup(void);
void stats_record_latency(cmd_type_t type, double ms);
void stats_record_throughput(int ops_per_sec);
void stats_record_error(cmd_type_t type, int error_code);
int  stats_get_total_errors(void);
int  stats_get_type_errors(cmd_type_t type);
void stats_report(char *buf, size_t buflen);

#endif /* STATS_H */
""")

    # ----------------------------------------------------------------
    # 7. stats.c — extracted from dispatch.c
    # ----------------------------------------------------------------
    write_file("stats.c", r"""#include "stats.h"
#include <stdio.h>
#include <string.h>

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
""")

    # ----------------------------------------------------------------
    # 8. dispatch.c — stats extracted, helper consolidated, int returns,
    #                  preserve magic
    # ----------------------------------------------------------------
    write_file("dispatch.c", r"""#include "dispatch.h"
#include "stats.h"
#include <stdio.h>
#include <string.h>
#include <time.h>

void dispatch_ctx_init(dispatch_ctx_t *ctx, int id, const char *source,
                       CMD_ALLOC_STRATEGY strat) {
    if (!ctx) return;
    ctx->magic = FRAMEWORK_MAGIC;
    ctx->id = id;
    ctx->source = source;
    ctx->alloc_strategy = strat;
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

/*
 * Consolidated handler execution helper.
 * Manages allocation strategy save/restore, timing, and stats recording
 * for a single handler invocation.
 */
static int execute_handler(dispatch_ctx_t *ctx, cmd_type_t type,
                           handler_func_t handler,
                           const char *payload, size_t len,
                           CMD_ALLOC_STRATEGY alloc) {
    CMD_ALLOC_STRATEGY saved = ctx->alloc_strategy;
    ctx->alloc_strategy = alloc;
    ctx->last_error = 0;
    ctx->error_msg[0] = '\0';

    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);

    int rc = handler(ctx, payload, len);

    clock_gettime(CLOCK_MONOTONIC, &end);
    double ms = (end.tv_sec - start.tv_sec) * 1000.0 +
                (end.tv_nsec - start.tv_nsec) / 1e6;
    stats_record_latency(type, ms);

    if (rc != 0) {
        stats_record_error(type, rc);
    }

    ctx->alloc_strategy = saved;
    return rc;
}

int dispatch_command(dispatch_ctx_t *ctx, cmd_type_t type,
                     const char *payload, size_t len) {
    if (!ctx) return -100;

    handler_func_t handler = get_handler_for_type(type);
    if (!handler) {
        ctx->last_error = -100;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "no handler for command type %d", type);
        stats_record_error(type, -100);
        return -100;
    }

    return execute_handler(ctx, type, handler, payload, len,
                           ctx->alloc_strategy);
}

int dispatch_pipeline(dispatch_ctx_t *ctx, cmd_entry_t *entries, int count) {
    if (!ctx || !entries || count <= 0) return -1;

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
                return -100;
            }
        }

        int rc = execute_handler(ctx, e->type, h,
                                 e->name, e->name ? strlen(e->name) : 0,
                                 e->alloc);
        if (rc != 0) {
            return rc;  /* Short-circuit on first error */
        }
    }
    return 0;
}
""")

    # ----------------------------------------------------------------
    # 9. main.c — updated for new API, preserve magic check
    # ----------------------------------------------------------------
    write_file("main.c", r"""#include "dispatch.h"
#include "handlers.h"
#include "stats.h"
#include <stdio.h>
#include <string.h>

int main(int argc, char *argv[]) {
    (void)argc;
    (void)argv;

    stats_init();

    dispatch_ctx_t ctx;
    dispatch_ctx_init(&ctx, 1, "main", CMD_ALLOC_HEAP);

    if (ctx.magic != FRAMEWORK_MAGIC) {
        fprintf(stderr, "FATAL: framework magic mismatch\n");
        return 1;
    }

    int rc;

    /* Single command dispatches */
    rc = dispatch_command(&ctx, CMD_QUERY, "SELECT * FROM users", 20);
    printf("query ok: rc=%d\n", rc);

    rc = dispatch_command(&ctx, CMD_INSERT, "DUPLICATE key=1", 15);
    printf("insert dup: rc=%d msg=%s\n", rc, ctx.error_msg);

    rc = dispatch_command(&ctx, CMD_UPDATE, "SET name='test'", 15);
    printf("update ok: rc=%d\n", rc);

    /* Successful pipeline */
    cmd_entry_t pipeline[] = {
        { CMD_QUERY,  "data1", NULL, CMD_ALLOC_STACK },
        { CMD_INSERT, "data2", NULL, CMD_ALLOC_HEAP },
        { CMD_DELETE, "data3", NULL, CMD_ALLOC_POOL },
    };
    rc = dispatch_pipeline(&ctx, pipeline, 3);
    printf("pipeline done: rc=%d\n", rc);

    /* Error pipeline — stops at entry 1 */
    cmd_entry_t err_pipeline[] = {
        { CMD_QUERY,  "data1",     NULL, CMD_ALLOC_STACK },
        { CMD_INSERT, "DUPLICATE", NULL, CMD_ALLOC_HEAP },
        { CMD_DELETE, "data3",     NULL, CMD_ALLOC_POOL },
    };
    rc = dispatch_pipeline(&ctx, err_pipeline, 3);
    printf("error pipeline: rc=%d msg=%s\n", rc, ctx.error_msg);

    /* Report */
    char report[2048];
    stats_report(report, sizeof(report));
    printf("%s", report);

    /* Enum conversion */
    printf("strategy heap name: %s\n",
           cmd_alloc_strategy_name(CMD_ALLOC_HEAP));
    printf("strategy from 'pool': %d\n",
           cmd_alloc_strategy_from_name("pool"));

    dispatch_ctx_cleanup(&ctx);
    stats_cleanup();

    return 0;
}
""")

    # ----------------------------------------------------------------
    # 10. Makefile — add stats.c (uses regular string for \t tabs)
    # ----------------------------------------------------------------
    write_file("Makefile", "CC = gcc\n"
        "CFLAGS = -Wall -Wextra -std=c11 -D_GNU_SOURCE -g -O2\n"
        "LDFLAGS =\n"
        "\n"
        "SRCS = main.c dispatch.c handlers.c types.c stats.c\n"
        "OBJS = $(SRCS:.c=.o)\n"
        "TARGET = cmdproc\n"
        "\n"
        ".PHONY: all clean\n"
        "\n"
        "all: $(TARGET)\n"
        "\n"
        "$(TARGET): $(OBJS)\n"
        "\t$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)\n"
        "\n"
        "%.o: %.c\n"
        "\t$(CC) $(CFLAGS) -c -o $@ $<\n"
        "\n"
        "clean:\n"
        "\trm -f $(OBJS) $(TARGET)\n"
        "\n"
        "dispatch.o: dispatch.c dispatch.h handlers.h types.h stats.h\n"
        "handlers.o: handlers.c handlers.h dispatch.h types.h\n"
        "types.o: types.c types.h\n"
        "stats.o: stats.c stats.h types.h\n"
        "main.o: main.c dispatch.h handlers.h types.h stats.h\n")

    print("=== Refactoring complete ===")


if __name__ == "__main__":
    refactor()
