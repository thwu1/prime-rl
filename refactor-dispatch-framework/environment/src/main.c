#include "dispatch.h"
#include "handlers.h"
#include <stdio.h>
#include <string.h>

int main(int argc, char *argv[]) {
    (void)argc;
    (void)argv;

    stats_init();

    dispatch_ctx_t ctx;
    dispatch_ctx_init(&ctx, 1, "main", CMD_MEMORY_MODE_HEAP);

    /* Verify framework integrity */
    if (ctx.magic != FRAMEWORK_MAGIC) {
        fprintf(stderr, "FATAL: framework magic mismatch\n");
        return 1;
    }

    /* --- Single command dispatches --- */
    dispatch_command(&ctx, CMD_QUERY, "SELECT * FROM users", 20);
    printf("query ok: error=%d\n", ctx.last_error);

    dispatch_command(&ctx, CMD_INSERT, "DUPLICATE key=1", 15);
    printf("insert dup: error=%d msg=%s\n", ctx.last_error, ctx.error_msg);

    dispatch_command(&ctx, CMD_UPDATE, "SET name='test'", 15);
    printf("update ok: error=%d\n", ctx.last_error);

    /* --- Successful pipeline --- */
    cmd_entry_t pipeline[] = {
        { CMD_QUERY,  "data1", NULL, CMD_MEMORY_MODE_STACK },
        { CMD_INSERT, "data2", NULL, CMD_MEMORY_MODE_HEAP },
        { CMD_DELETE, "data3", NULL, CMD_MEMORY_MODE_POOL },
    };
    dispatch_pipeline(&ctx, pipeline, 3);
    printf("pipeline done: error=%d\n", ctx.last_error);

    /* --- Error pipeline (should stop at entry 1 after refactoring) --- */
    cmd_entry_t err_pipeline[] = {
        { CMD_QUERY,  "data1",     NULL, CMD_MEMORY_MODE_STACK },
        { CMD_INSERT, "DUPLICATE", NULL, CMD_MEMORY_MODE_HEAP },
        { CMD_DELETE, "data3",     NULL, CMD_MEMORY_MODE_POOL },
    };
    dispatch_pipeline(&ctx, err_pipeline, 3);
    printf("error pipeline: error=%d msg=%s\n", ctx.last_error, ctx.error_msg);

    /* --- Print report --- */
    char report[2048];
    stats_report(report, sizeof(report));
    printf("%s", report);

    /* --- Enum conversion --- */
    printf("mode heap name: %s\n",
           cmd_memory_mode_name(CMD_MEMORY_MODE_HEAP));
    printf("mode from 'pool': %d\n",
           cmd_memory_mode_from_name("pool"));

    dispatch_ctx_cleanup(&ctx);
    stats_cleanup();

    return 0;
}
