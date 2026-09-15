/*
 * gen_golden.c - Generate golden binary reference records using the original API.
 * Run once at Docker build time; outputs are used to verify wire format compatibility.
 */

#include "record.h"
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int write_bin(const char *path, const uint8_t *data, size_t len) {
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); return -1; }
    if (fwrite(data, 1, len, f) != len) { fclose(f); return -1; }
    fclose(f);
    return 0;
}

int main(void) {
    uint8_t buf[1024];
    size_t n;
    record_t rec;

    mkdir("golden", 0755);

    /* Metric */
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_METRIC;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.metric.name, "sys.cpu.idle", sizeof(rec.data.metric.name));
    rec.data.metric.value = 73.25;
    rec.data.metric.sample_time = 1700000000000000ULL;
    n = rec_serialize(&rec, buf, sizeof(buf));
    if (n == 0 || write_bin("golden/metric.bin", buf, n) != 0) return 1;

    /* Log */
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_LOG;
    rec.header.timestamp_us = 1700000000000000ULL;
    rec.data.log.level = 3;
    strncpy(rec.data.log.source, "auth-svc", sizeof(rec.data.log.source));
    strncpy(rec.data.log.message, "login failed for user root", sizeof(rec.data.log.message));
    n = rec_serialize(&rec, buf, sizeof(buf));
    if (n == 0 || write_bin("golden/log.bin", buf, n) != 0) return 1;

    /* Alert */
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_ALERT;
    rec.header.timestamp_us = 1700000000000000ULL;
    rec.data.alert.severity = 5;
    strncpy(rec.data.alert.rule, "disk_full", sizeof(rec.data.alert.rule));
    strncpy(rec.data.alert.detail, "/dev/sda1 at 98%", sizeof(rec.data.alert.detail));
    n = rec_serialize(&rec, buf, sizeof(buf));
    if (n == 0 || write_bin("golden/alert.bin", buf, n) != 0) return 1;

    /* Trace */
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_TRACE;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.trace.trace_id, "t-9f8e7d6c5b4a3210", sizeof(rec.data.trace.trace_id));
    strncpy(rec.data.trace.span_id, "s-1234abcd", sizeof(rec.data.trace.span_id));
    strncpy(rec.data.trace.parent_id, "p-0000root", sizeof(rec.data.trace.parent_id));
    strncpy(rec.data.trace.operation, "pg.query.select", sizeof(rec.data.trace.operation));
    rec.data.trace.duration_us = 4821;
    rec.data.trace.status = 0;
    n = rec_serialize(&rec, buf, sizeof(buf));
    if (n == 0 || write_bin("golden/trace.bin", buf, n) != 0) return 1;

    /* Audit */
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_AUDIT;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.audit.user, "deploy-bot", sizeof(rec.data.audit.user));
    strncpy(rec.data.audit.action, "restart", sizeof(rec.data.audit.action));
    strncpy(rec.data.audit.resource, "/cluster/prod/node-7", sizeof(rec.data.audit.resource));
    rec.data.audit.outcome = 1;
    n = rec_serialize(&rec, buf, sizeof(buf));
    if (n == 0 || write_bin("golden/audit.bin", buf, n) != 0) return 1;

    printf("Generated golden binary records in golden/\n");
    return 0;
}
