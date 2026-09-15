#ifndef DISPATCH_H
#define DISPATCH_H

#include "types.h"

typedef struct dispatch_ctx {
    unsigned long magic;      /* Set to FRAMEWORK_MAGIC by dispatch_ctx_init */
    int id;
    const char *source;
    CMD_MEMORY_MODE mem_mode;
    void *user_data;
    int last_error;
    char error_msg[256];
} dispatch_ctx_t;

/*
 * Handler function pointer type.
 * Currently returns void — callers must inspect ctx->last_error
 * after invocation to detect failures.
 */
typedef void (*handler_func_t)(dispatch_ctx_t *ctx,
                                const char *payload, size_t len);

#include "handlers.h"  /* pulls in handler declarations */

typedef struct cmd_entry {
    cmd_type_t type;
    const char *name;
    handler_func_t handler;
    CMD_MEMORY_MODE alloc;
} cmd_entry_t;

/* Context lifecycle */
void dispatch_ctx_init(dispatch_ctx_t *ctx, int id, const char *source,
                       CMD_MEMORY_MODE mode);
void dispatch_ctx_cleanup(dispatch_ctx_t *ctx);

/* Dispatch a single command */
void dispatch_command(dispatch_ctx_t *ctx, cmd_type_t type,
                      const char *payload, size_t len);

/* Execute a pipeline of commands */
void dispatch_pipeline(dispatch_ctx_t *ctx, cmd_entry_t *entries, int count);

/* ----------------------------------------------------------------
 * Statistics tracking — these are embedded here but logically
 * belong in a separate module.
 * ---------------------------------------------------------------- */
void stats_init(void);
void stats_cleanup(void);
void stats_record_latency(cmd_type_t type, double ms);
void stats_record_throughput(int ops_per_sec);
void stats_record_error(cmd_type_t type, int error_code);
int  stats_get_total_errors(void);
int  stats_get_type_errors(cmd_type_t type);
void stats_report(char *buf, size_t buflen);

#endif /* DISPATCH_H */
