#include "handlers.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/*
 * Handler-specific error codes.
 * Each handler uses a unique negative error code for its domain-specific
 * failure mode, plus a shared -17 for null/invalid argument errors.
 */

void handle_query(dispatch_ctx_t *ctx, const char *payload, size_t len) {
    if (!ctx || !payload || len == 0) {
        if (ctx) {
            ctx->last_error = -17;
            snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                     "query: invalid arguments");
        }
        return;
    }
    /* Reject queries starting with "INVALID" */
    if (len >= 7 && strncmp(payload, "INVALID", 7) == 0) {
        ctx->last_error = -23;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "query: syntax error in '%.*s'", (int)len, payload);
        return;
    }
    ctx->last_error = 0;
}

void handle_insert(dispatch_ctx_t *ctx, const char *payload, size_t len) {
    if (!ctx || !payload || len == 0) {
        if (ctx) {
            ctx->last_error = -17;
            snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                     "insert: invalid arguments");
        }
        return;
    }
    if (len >= 9 && strncmp(payload, "DUPLICATE", 9) == 0) {
        ctx->last_error = -29;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "insert: duplicate key in '%.*s'", (int)len, payload);
        return;
    }
    ctx->last_error = 0;
}

void handle_update(dispatch_ctx_t *ctx, const char *payload, size_t len) {
    if (!ctx || !payload || len == 0) {
        if (ctx) {
            ctx->last_error = -17;
            snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                     "update: invalid arguments");
        }
        return;
    }
    if (len >= 8 && strncmp(payload, "CONFLICT", 8) == 0) {
        ctx->last_error = -37;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "update: write conflict on '%.*s'", (int)len, payload);
        return;
    }
    ctx->last_error = 0;
}

void handle_delete(dispatch_ctx_t *ctx, const char *payload, size_t len) {
    if (!ctx || !payload || len == 0) {
        if (ctx) {
            ctx->last_error = -17;
            snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                     "delete: invalid arguments");
        }
        return;
    }
    if (len >= 9 && strncmp(payload, "PROTECTED", 9) == 0) {
        ctx->last_error = -41;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "delete: protected record '%.*s'", (int)len, payload);
        return;
    }
    ctx->last_error = 0;
}

void handle_batch(dispatch_ctx_t *ctx, const char *payload, size_t len) {
    if (!ctx || !payload || len == 0) {
        if (ctx) {
            ctx->last_error = -17;
            snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                     "batch: invalid arguments");
        }
        return;
    }
    if (len >= 8 && strncmp(payload, "TOOLARGE", 8) == 0) {
        ctx->last_error = -47;
        snprintf(ctx->error_msg, sizeof(ctx->error_msg),
                 "batch: payload too large (%zu bytes)", len);
        return;
    }
    ctx->last_error = 0;
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
