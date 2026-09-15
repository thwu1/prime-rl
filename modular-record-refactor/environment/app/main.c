/*
 * main.c - Example usage of the record processing library
 */

#include "record.h"
#include <stdio.h>
#include <string.h>

int main(void) {
    /* Build a metric record in-memory */
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_METRIC;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.metric.name, "cpu.usage", sizeof(rec.data.metric.name));
    rec.data.metric.value = 42.5;
    rec.data.metric.sample_time = 1700000000000000ULL;

    /* Serialize to wire format */
    uint8_t buf[1024];
    size_t n = rec_serialize(&rec, buf, sizeof(buf));
    if (n == 0) {
        fprintf(stderr, "serialize failed: %s\n", rec_strerror());
        return 1;
    }
    printf("Serialized %zu bytes\n", n);

    /* Parse back from wire format */
    record_t parsed;
    rec_parse(buf, n, &parsed);
    if (rec_errno() != REC_OK) {
        fprintf(stderr, "parse failed: %s\n", rec_strerror());
        return 1;
    }

    /* Human-readable output */
    char *s = rec_format(&parsed);
    if (s) {
        printf("Parsed: %s\n", s);
    }

    return 0;
}
