/*
 * test_driver.c — Functional test for the refactored command dispatch API.
 *
 * Verifies that the refactored API works correctly by checking exact
 * return values, framework integrity constants, and pipeline behavior.
 * Each VERIFY line prints a specific computed value that pytest checks.
 *
 */

#include <stdio.h>
#include <string.h>
#include <assert.h>

/* Include stats.h first to verify it's self-contained */
#include "stats.h"

/* Include handlers.h WITHOUT dispatch.h to verify no circular dep */
#include "handlers.h"

/* Now include dispatch.h for full context struct + entry struct */
#include "dispatch.h"

int main(void) {
    int rc;

    stats_init();

    dispatch_ctx_t ctx;
    dispatch_ctx_init(&ctx, 1, "test_driver", CMD_ALLOC_HEAP);

    /* Test 1: framework magic integrity */
    assert(ctx.magic == FRAMEWORK_MAGIC);
    assert(ctx.magic == 0xA7F3C9E2UL);
    printf("VERIFY:magic=0x%lx\n", (unsigned long)ctx.magic);

    /* Test 2: handler null-arg error code */
    rc = handle_query(&ctx, NULL, 0);
    assert(rc == -17);
    printf("VERIFY:query_null=%d\n", rc);

    /* Test 3: handler-specific error codes */
    rc = handle_query(&ctx, "INVALID_SQL", 11);
    assert(rc == -23);
    printf("VERIFY:query_invalid=%d\n", rc);

    rc = handle_insert(&ctx, "DUPLICATE_KEY", 13);
    assert(rc == -29);
    printf("VERIFY:insert_dup=%d\n", rc);

    rc = handle_update(&ctx, "CONFLICT_ROW", 12);
    assert(rc == -37);
    printf("VERIFY:update_conflict=%d\n", rc);

    rc = handle_delete(&ctx, "PROTECTED_REC", 13);
    assert(rc == -41);
    printf("VERIFY:delete_protected=%d\n", rc);

    rc = handle_batch(&ctx, "TOOLARGE_DATA", 13);
    assert(rc == -47);
    printf("VERIFY:batch_toolarge=%d\n", rc);

    /* Test 4: handler success returns 0 */
    rc = handle_query(&ctx, "SELECT 1", 8);
    assert(rc == 0);
    rc = handle_insert(&ctx, "new_record", 10);
    assert(rc == 0);
    rc = handle_update(&ctx, "SET x=1", 7);
    assert(rc == 0);
    rc = handle_delete(&ctx, "id=42", 5);
    assert(rc == 0);
    rc = handle_batch(&ctx, "items", 5);
    assert(rc == 0);
    printf("VERIFY:all_handlers_success=0\n");

    /* Test 5: dispatch_command propagates exact error code */
    rc = dispatch_command(&ctx, CMD_QUERY, "valid query", 11);
    assert(rc == 0);
    printf("VERIFY:dispatch_cmd_ok=%d\n", rc);

    rc = dispatch_command(&ctx, CMD_INSERT, "DUPLICATE_X", 11);
    assert(rc == -29);
    printf("VERIFY:dispatch_cmd_err=%d\n", rc);

    /* Test 6: pipeline success */
    cmd_entry_t good_pipeline[] = {
        { CMD_QUERY,  "q1",  NULL, CMD_ALLOC_STACK },
        { CMD_INSERT, "i1",  NULL, CMD_ALLOC_HEAP },
        { CMD_DELETE, "d1",  NULL, CMD_ALLOC_POOL },
    };
    rc = dispatch_pipeline(&ctx, good_pipeline, 3);
    assert(rc == 0);
    printf("VERIFY:pipeline_ok=%d\n", rc);

    /* Test 7: pipeline short-circuit verification */
    stats_cleanup();
    stats_init();

    cmd_entry_t sc_pipeline[] = {
        { CMD_QUERY,  "ok_query",   NULL, CMD_ALLOC_STACK },
        { CMD_INSERT, "DUPLICATE",  NULL, CMD_ALLOC_HEAP },
        { CMD_DELETE, "PROTECTED",  NULL, CMD_ALLOC_POOL },
    };
    rc = dispatch_pipeline(&ctx, sc_pipeline, 3);
    assert(rc == -29);

    int insert_errs = stats_get_type_errors(CMD_INSERT);
    int delete_errs = stats_get_type_errors(CMD_DELETE);
    assert(insert_errs == 1);
    assert(delete_errs == 0);
    printf("VERIFY:pipeline_sc=%d,insert_errs=%d,delete_errs=%d\n",
           rc, insert_errs, delete_errs);

    /* Test 8: enum rename and values */
    CMD_ALLOC_STRATEGY strat = CMD_ALLOC_HEAP;
    const char *name = cmd_alloc_strategy_name(strat);
    assert(strcmp(name, "heap") == 0);
    printf("VERIFY:alloc_name=%s\n", name);

    CMD_ALLOC_STRATEGY parsed = cmd_alloc_strategy_from_name("pool");
    assert(parsed == CMD_ALLOC_POOL);
    assert(parsed == 3);
    printf("VERIFY:alloc_parse=%d\n", parsed);

    int enum_sum = CMD_ALLOC_NONE + CMD_ALLOC_STACK + CMD_ALLOC_HEAP + CMD_ALLOC_POOL;
    assert(enum_sum == 6);
    printf("VERIFY:enum_sum=%d\n", enum_sum);

    /* Test 9: stats module independence */
    stats_cleanup();
    stats_init();
    stats_record_error(CMD_QUERY, -23);
    stats_record_error(CMD_INSERT, -29);
    stats_record_error(CMD_INSERT, -29);
    stats_record_latency(CMD_QUERY, 1.5);

    int total_errs = stats_get_total_errors();
    assert(total_errs == 3);
    printf("VERIFY:total_errors=%d\n", total_errs);

    int query_errs = stats_get_type_errors(CMD_QUERY);
    int insert_errs2 = stats_get_type_errors(CMD_INSERT);
    assert(query_errs == 1);
    assert(insert_errs2 == 2);
    printf("VERIFY:query_errs=%d,insert_errs=%d\n", query_errs, insert_errs2);

    char report[1024];
    stats_report(report, sizeof(report));
    assert(strlen(report) > 10);
    printf("VERIFY:report_len=%d\n", (int)strlen(report));

    dispatch_ctx_cleanup(&ctx);
    stats_cleanup();

    printf("ALL_TESTS_PASSED\n");
    return 0;
}
