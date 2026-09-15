/*
 * test_functional.c - Functional tests for the refactored record library
 *
 * Tests the NEW API signatures:
 *   int rec_parse(const uint8_t*, size_t, record_t*, rec_error_t*)
 *   int rec_validate(const record_t*, rec_error_t*)
 *   int rec_format(const record_t*, char*, size_t)
 *   size_t rec_serialize(const record_t*, uint8_t*, size_t, rec_error_t*)
 *   uint32_t rec_crc32(const uint8_t*, size_t)
 *
 */

#include "record.h"
#include <string.h>
#include <stdio.h>

static int tests_passed = 0;
static int tests_run = 0;

#define RUN_TEST(fn) do { \
    tests_run++; \
    printf("  %-35s ", #fn); \
    if (fn()) { tests_passed++; printf("PASS\n"); } \
    else { printf("FAIL\n"); } \
} while (0)

/* ---- CRC32 correctness ---- */

int test_crc32_known_value(void) {
    /* Standard CRC32 test vector: CRC32("123456789") = 0xCBF43926 */
    uint32_t crc = rec_crc32((const uint8_t *)"123456789", 9);
    if (crc != 0xCBF43926u) {
        fprintf(stderr, "    got 0x%08X, expected 0xCBF43926\n", crc);
        return 0;
    }
    return 1;
}

int test_crc32_empty(void) {
    uint32_t crc = rec_crc32((const uint8_t *)"", 0);
    if (crc != 0x00000000u) {
        fprintf(stderr, "    got 0x%08X, expected 0x00000000\n", crc);
        return 0;
    }
    return 1;
}

/* ---- Error handling API ---- */

int test_parse_returns_error_code(void) {
    record_t rec;
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    uint8_t bad[] = {0xFF, 0xFF, 0, 0};
    int ret = rec_parse(bad, sizeof(bad), &rec, &err);
    if (ret == 0) {
        fprintf(stderr, "    expected non-zero return for bad magic\n");
        return 0;
    }
    if (err.code == 0) {
        fprintf(stderr, "    err.code not set\n");
        return 0;
    }
    return 1;
}

int test_parse_null_input(void) {
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(NULL, 0, NULL, &err);
    return (ret != 0);
}

int test_parse_short_buffer(void) {
    uint8_t buf[5] = {0xCD, 0xAB, 1, 1, 0};
    record_t rec;
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, sizeof(buf), &rec, &err);
    return (ret != 0);
}

int test_validate_returns_error_code(void) {
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = 0xDEAD;
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    int ret = rec_validate(&rec, &err);
    return (ret != 0);
}

/* ---- Metric roundtrip ---- */

int test_metric_roundtrip(void) {
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_METRIC;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.metric.name, "cpu.idle", sizeof(rec.data.metric.name));
    rec.data.metric.value = 99.5;
    rec.data.metric.sample_time = 1700000000000000ULL;

    uint8_t buf[1024];
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    size_t n = rec_serialize(&rec, buf, sizeof(buf), &err);
    if (n == 0) { fprintf(stderr, "    serialize: %s\n", err.message); return 0; }

    record_t parsed;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &parsed, &err);
    if (ret != 0) { fprintf(stderr, "    parse: %s\n", err.message); return 0; }

    if (strcmp(parsed.data.metric.name, "cpu.idle") != 0) return 0;
    if (parsed.data.metric.value != 99.5) return 0;
    if (parsed.data.metric.sample_time != 1700000000000000ULL) return 0;
    if (parsed.header.type != REC_METRIC) return 0;
    return 1;
}

/* ---- Log roundtrip ---- */

int test_log_roundtrip(void) {
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_LOG;
    rec.header.timestamp_us = 1700000000000000ULL;
    rec.data.log.level = 2;
    strncpy(rec.data.log.source, "myapp", sizeof(rec.data.log.source));
    strncpy(rec.data.log.message, "something happened", sizeof(rec.data.log.message));

    uint8_t buf[1024];
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    size_t n = rec_serialize(&rec, buf, sizeof(buf), &err);
    if (n == 0) return 0;

    record_t parsed;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &parsed, &err);
    if (ret != 0) return 0;

    if (parsed.data.log.level != 2) return 0;
    if (strcmp(parsed.data.log.source, "myapp") != 0) return 0;
    if (strcmp(parsed.data.log.message, "something happened") != 0) return 0;
    return 1;
}

/* ---- Alert roundtrip ---- */

int test_alert_roundtrip(void) {
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_ALERT;
    rec.header.timestamp_us = 1700000000000000ULL;
    rec.data.alert.severity = 4;
    strncpy(rec.data.alert.rule, "high_cpu", sizeof(rec.data.alert.rule));
    strncpy(rec.data.alert.detail, "CPU above 90 percent", sizeof(rec.data.alert.detail));

    uint8_t buf[1024];
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    size_t n = rec_serialize(&rec, buf, sizeof(buf), &err);
    if (n == 0) return 0;

    record_t parsed;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &parsed, &err);
    if (ret != 0) return 0;

    if (parsed.data.alert.severity != 4) return 0;
    if (strcmp(parsed.data.alert.rule, "high_cpu") != 0) return 0;
    if (strcmp(parsed.data.alert.detail, "CPU above 90 percent") != 0) return 0;
    return 1;
}

/* ---- Trace roundtrip ---- */

int test_trace_roundtrip(void) {
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_TRACE;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.trace.trace_id, "abc123", sizeof(rec.data.trace.trace_id));
    strncpy(rec.data.trace.span_id, "span001", sizeof(rec.data.trace.span_id));
    strncpy(rec.data.trace.parent_id, "root", sizeof(rec.data.trace.parent_id));
    strncpy(rec.data.trace.operation, "db.query", sizeof(rec.data.trace.operation));
    rec.data.trace.duration_us = 12345;
    rec.data.trace.status = 0;

    uint8_t buf[1024];
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    size_t n = rec_serialize(&rec, buf, sizeof(buf), &err);
    if (n == 0) return 0;

    record_t parsed;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &parsed, &err);
    if (ret != 0) return 0;

    if (strcmp(parsed.data.trace.trace_id, "abc123") != 0) return 0;
    if (strcmp(parsed.data.trace.span_id, "span001") != 0) return 0;
    if (parsed.data.trace.duration_us != 12345) return 0;
    if (parsed.data.trace.status != 0) return 0;
    return 1;
}

/* ---- Audit roundtrip ---- */

int test_audit_roundtrip(void) {
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_AUDIT;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.audit.user, "admin", sizeof(rec.data.audit.user));
    strncpy(rec.data.audit.action, "delete", sizeof(rec.data.audit.action));
    strncpy(rec.data.audit.resource, "/api/users/42", sizeof(rec.data.audit.resource));
    rec.data.audit.outcome = 1;

    uint8_t buf[1024];
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    size_t n = rec_serialize(&rec, buf, sizeof(buf), &err);
    if (n == 0) return 0;

    record_t parsed;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &parsed, &err);
    if (ret != 0) return 0;

    if (strcmp(parsed.data.audit.user, "admin") != 0) return 0;
    if (strcmp(parsed.data.audit.action, "delete") != 0) return 0;
    if (strcmp(parsed.data.audit.resource, "/api/users/42") != 0) return 0;
    if (parsed.data.audit.outcome != 1) return 0;
    return 1;
}

/* ---- Format with buffer ---- */

int test_format_metric_buffer(void) {
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_METRIC;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.metric.name, "test.metric", sizeof(rec.data.metric.name));
    rec.data.metric.value = 3.14;
    rec.data.metric.sample_time = 1700000000000000ULL;

    char buf[512];
    int ret = rec_format(&rec, buf, sizeof(buf));
    if (ret < 0) { fprintf(stderr, "    format returned %d\n", ret); return 0; }
    if (strstr(buf, "METRIC") == NULL) { fprintf(stderr, "    missing METRIC\n"); return 0; }
    if (strstr(buf, "test.metric") == NULL) { fprintf(stderr, "    missing name\n"); return 0; }
    return 1;
}

int test_format_log_buffer(void) {
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_LOG;
    rec.header.timestamp_us = 1700000000000000ULL;
    rec.data.log.level = 3;
    strncpy(rec.data.log.source, "svc", sizeof(rec.data.log.source));
    strncpy(rec.data.log.message, "error occurred", sizeof(rec.data.log.message));

    char buf[512];
    int ret = rec_format(&rec, buf, sizeof(buf));
    if (ret < 0) return 0;
    if (strstr(buf, "LOG") == NULL) return 0;
    if (strstr(buf, "svc") == NULL) return 0;
    return 1;
}

/* ---- Bad CRC detection ---- */

int test_bad_crc_detected(void) {
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_METRIC;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.metric.name, "test", sizeof(rec.data.metric.name));
    rec.data.metric.value = 1.0;
    rec.data.metric.sample_time = 1700000000000000ULL;

    uint8_t buf[1024];
    rec_error_t err;
    memset(&err, 0, sizeof(err));
    size_t n = rec_serialize(&rec, buf, sizeof(buf), &err);
    if (n == 0) return 0;

    /* Corrupt a payload byte */
    buf[REC_HDR_SIZE + 5] ^= 0xFF;

    record_t parsed;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &parsed, &err);
    return (ret != 0);
}

int main(void) {
    printf("Functional tests for refactored record library\n");
    printf("===============================================\n");

    RUN_TEST(test_crc32_known_value);
    RUN_TEST(test_crc32_empty);
    RUN_TEST(test_parse_returns_error_code);
    RUN_TEST(test_parse_null_input);
    RUN_TEST(test_parse_short_buffer);
    RUN_TEST(test_validate_returns_error_code);
    RUN_TEST(test_metric_roundtrip);
    RUN_TEST(test_log_roundtrip);
    RUN_TEST(test_alert_roundtrip);
    RUN_TEST(test_trace_roundtrip);
    RUN_TEST(test_audit_roundtrip);
    RUN_TEST(test_format_metric_buffer);
    RUN_TEST(test_format_log_buffer);
    RUN_TEST(test_bad_crc_detected);

    printf("\nResults: %d/%d passed\n", tests_passed, tests_run);
    return (tests_passed == tests_run) ? 0 : 1;
}
