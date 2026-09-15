/*
 * test_golden.c - Binary compatibility tests against golden reference data
 *
 * Parses binary records serialized by the ORIGINAL code and verifies
 * field-level correctness plus byte-level round-trip identity, ensuring
 * the refactored library preserves the exact wire format.
 *
 */

#include "record.h"
#include <string.h>
#include <stdio.h>
#include <math.h>

static int tests_passed = 0;
static int tests_run = 0;

#define RUN_TEST(fn) do { \
    tests_run++; \
    printf("  %-40s ", #fn); \
    if (fn()) { tests_passed++; printf("PASS\n"); } \
    else { printf("FAIL\n"); } \
} while (0)

static size_t read_file(const char *path, uint8_t *buf, size_t maxlen) {
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "Cannot open %s\n", path); return 0; }
    size_t n = fread(buf, 1, maxlen, f);
    fclose(f);
    return n;
}

/* Verify parse + re-serialize produces identical bytes */
static int roundtrip_check(const uint8_t *orig, size_t orig_len,
                           const record_t *rec) {
    uint8_t buf2[1024];
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    size_t n2 = rec_serialize(rec, buf2, sizeof(buf2), &err);
    if (n2 != orig_len) {
        fprintf(stderr, "    size mismatch: %zu vs %zu\n", n2, orig_len);
        return 0;
    }
    if (memcmp(orig, buf2, orig_len) != 0) {
        fprintf(stderr, "    byte mismatch in re-serialization\n");
        return 0;
    }
    return 1;
}

int test_golden_metric(void) {
    uint8_t buf[1024];
    size_t n = read_file("/app/golden/metric.bin", buf, sizeof(buf));
    if (n == 0) return 0;

    record_t rec;
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &rec, &err);
    if (ret != 0) { fprintf(stderr, "    parse: %s\n", err.message); return 0; }

    if (rec.header.type != REC_METRIC) return 0;
    if (rec.header.timestamp_us != 1700000000000000ULL) return 0;
    if (strcmp(rec.data.metric.name, "sys.cpu.idle") != 0) return 0;
    if (fabs(rec.data.metric.value - 73.25) > 0.001) return 0;
    if (rec.data.metric.sample_time != 1700000000000000ULL) return 0;

    return roundtrip_check(buf, n, &rec);
}

int test_golden_log(void) {
    uint8_t buf[1024];
    size_t n = read_file("/app/golden/log.bin", buf, sizeof(buf));
    if (n == 0) return 0;

    record_t rec;
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &rec, &err);
    if (ret != 0) { fprintf(stderr, "    parse: %s\n", err.message); return 0; }

    if (rec.header.type != REC_LOG) return 0;
    if (rec.data.log.level != 3) return 0;
    if (strcmp(rec.data.log.source, "auth-svc") != 0) return 0;
    if (strcmp(rec.data.log.message, "login failed for user root") != 0) return 0;

    return roundtrip_check(buf, n, &rec);
}

int test_golden_alert(void) {
    uint8_t buf[1024];
    size_t n = read_file("/app/golden/alert.bin", buf, sizeof(buf));
    if (n == 0) return 0;

    record_t rec;
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &rec, &err);
    if (ret != 0) { fprintf(stderr, "    parse: %s\n", err.message); return 0; }

    if (rec.header.type != REC_ALERT) return 0;
    if (rec.data.alert.severity != 5) return 0;
    if (strcmp(rec.data.alert.rule, "disk_full") != 0) return 0;
    if (strcmp(rec.data.alert.detail, "/dev/sda1 at 98%") != 0) return 0;

    return roundtrip_check(buf, n, &rec);
}

int test_golden_trace(void) {
    uint8_t buf[1024];
    size_t n = read_file("/app/golden/trace.bin", buf, sizeof(buf));
    if (n == 0) return 0;

    record_t rec;
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &rec, &err);
    if (ret != 0) { fprintf(stderr, "    parse: %s\n", err.message); return 0; }

    if (rec.header.type != REC_TRACE) return 0;
    if (strcmp(rec.data.trace.trace_id, "t-9f8e7d6c5b4a3210") != 0) return 0;
    if (strcmp(rec.data.trace.span_id, "s-1234abcd") != 0) return 0;
    if (strcmp(rec.data.trace.parent_id, "p-0000root") != 0) return 0;
    if (strcmp(rec.data.trace.operation, "pg.query.select") != 0) return 0;
    if (rec.data.trace.duration_us != 4821) return 0;
    if (rec.data.trace.status != 0) return 0;

    return roundtrip_check(buf, n, &rec);
}

int test_golden_audit(void) {
    uint8_t buf[1024];
    size_t n = read_file("/app/golden/audit.bin", buf, sizeof(buf));
    if (n == 0) return 0;

    record_t rec;
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &rec, &err);
    if (ret != 0) { fprintf(stderr, "    parse: %s\n", err.message); return 0; }

    if (rec.header.type != REC_AUDIT) return 0;
    if (strcmp(rec.data.audit.user, "deploy-bot") != 0) return 0;
    if (strcmp(rec.data.audit.action, "restart") != 0) return 0;
    if (strcmp(rec.data.audit.resource, "/cluster/prod/node-7") != 0) return 0;
    if (rec.data.audit.outcome != 1) return 0;

    return roundtrip_check(buf, n, &rec);
}

int main(void) {
    printf("Golden binary compatibility tests\n");
    printf("==================================\n");

    RUN_TEST(test_golden_metric);
    RUN_TEST(test_golden_log);
    RUN_TEST(test_golden_alert);
    RUN_TEST(test_golden_trace);
    RUN_TEST(test_golden_audit);

    printf("\nResults: %d/%d passed\n", tests_passed, tests_run);
    return (tests_passed == tests_run) ? 0 : 1;
}
