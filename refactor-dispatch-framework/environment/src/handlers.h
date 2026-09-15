#ifndef HANDLERS_H
#define HANDLERS_H

#include <stddef.h>
#include "dispatch.h"  /* for dispatch_ctx_t, handler_func_t, cmd_type_t */

/*
 * Command handler functions.
 * Each handler processes a command payload within the given dispatch context.
 * Errors are signaled by setting ctx->last_error to a negative value.
 *
 * BUG: These return void, so callers cannot distinguish "handler ran
 * successfully" from "handler hasn't been called yet." The pipeline
 * relies on checking ctx->last_error after each call, but pre-existing
 * errors from earlier operations contaminate the check.
 */
void handle_query(dispatch_ctx_t *ctx, const char *payload, size_t len);
void handle_insert(dispatch_ctx_t *ctx, const char *payload, size_t len);
void handle_update(dispatch_ctx_t *ctx, const char *payload, size_t len);
void handle_delete(dispatch_ctx_t *ctx, const char *payload, size_t len);
void handle_batch(dispatch_ctx_t *ctx, const char *payload, size_t len);

handler_func_t get_handler_for_type(cmd_type_t type);

#endif /* HANDLERS_H */
