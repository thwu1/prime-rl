#!/usr/bin/env python3

"""
Refactor the monolithic record processing library into modular architecture.

Transformations:
  1. Compute CRC32 lookup table as compile-time const array
  2. Decompose record.c into: checksum.c, parser.c, validator.c,
     formatter.c, serializer.c
  3. Replace global error state with rec_error_t context parameter
  4. Replace void returns with int return codes
  5. Replace static format buffer with caller-provided buffer
  6. Create record_internal.h for shared helpers
  7. Update Makefile and main.c
"""

import os

APP_DIR = "/app"


def compute_crc32_table():
    """Compute standard CRC32 lookup table (polynomial 0xEDB88320)."""
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
        table.append(crc)
    return table


def format_crc_table_c(table):
    """Format CRC32 table as a C static const array declaration."""
    lines = ["static const uint32_t crc_table[256] = {"]
    for i in range(0, 256, 8):
        chunk = table[i:i + 8]
        vals = ", ".join(f"0x{v:08X}u" for v in chunk)
        lines.append(f"    {vals},")
    lines.append("};")
    return "\n".join(lines)


def write_file(name, content):
    path = os.path.join(APP_DIR, name)
    with open(path, "w") as f:
        f.write(content)
    print(f"  wrote {name} ({len(content)} bytes)")


def main():
    print("Refactoring record library...")

    # Step 1: Compute CRC32 table
    crc_table = compute_crc32_table()
    crc_table_c = format_crc_table_c(crc_table)

    # Verify table correctness: CRC32("123456789") should be 0xCBF43926
    def crc32_check(data):
        crc = 0xFFFFFFFF
        for b in data:
            crc = crc_table[(crc ^ b) & 0xFF] ^ (crc >> 8)
        return crc ^ 0xFFFFFFFF

    test_crc = crc32_check(b"123456789")
    assert test_crc == 0xCBF43926, f"CRC32 table verification failed: 0x{test_crc:08X}"
    print(f"  CRC32 table verified (test vector: 0x{test_crc:08X})")

    # Step 2: Remove old monolithic source
    old = os.path.join(APP_DIR, "record.c")
    if os.path.exists(old):
        os.remove(old)
        print("  removed old record.c")

    # Step 3: Write all refactored files
    write_file("record.h", RECORD_H)
    write_file("record_internal.h", RECORD_INTERNAL_H)
    write_file("checksum.c", CHECKSUM_C.replace("/* CRC_TABLE */", crc_table_c))
    write_file("parser.c", PARSER_C)
    write_file("validator.c", VALIDATOR_C)
    write_file("formatter.c", FORMATTER_C)
    write_file("serializer.c", SERIALIZER_C)
    write_file("Makefile", MAKEFILE)
    write_file("main.c", MAIN_C)

    print("Done.")


# ---------------------------------------------------------------------------
# Refactored file contents
# ---------------------------------------------------------------------------

RECORD_H = r"""/*
 * record.h - Public API for the binary record processing library
 */

#ifndef RECORD_H
#define RECORD_H

#include <stdint.h>
#include <stddef.h>

/* Record type constants */
#define REC_METRIC  1
#define REC_LOG     2
#define REC_ALERT   3
#define REC_TRACE   4
#define REC_AUDIT   5

/* Error codes */
#define REC_OK          0
#define REC_ERR_NULL    (-1)
#define REC_ERR_SHORT   (-2)
#define REC_ERR_MAGIC   (-3)
#define REC_ERR_CRC     (-4)
#define REC_ERR_TYPE    (-5)
#define REC_ERR_ALLOC   (-6)
#define REC_ERR_RANGE   (-7)

/* Protocol constants */
#define REC_MAGIC       0xABCD
#define REC_VERSION     1
#define REC_HDR_SIZE    20

/* Maximum sizes */
#define MAX_NAME_LEN        64
#define MAX_MSG_LEN         256
#define MAX_TRACE_ID_LEN    32
#define MAX_RESOURCE_LEN    128

/* Error context (replaces global error state) */
typedef struct {
    int  code;
    char message[256];
} rec_error_t;

/* Record header */
struct rec_header {
    uint16_t magic;
    uint8_t  version;
    uint8_t  type;
    uint32_t payload_len;
    uint64_t timestamp_us;
    uint32_t crc32;
};

/* Payload structures */
struct metric_data {
    char     name[MAX_NAME_LEN];
    double   value;
    uint64_t sample_time;
};

struct log_data {
    uint8_t  level;
    char     source[MAX_NAME_LEN];
    char     message[MAX_MSG_LEN];
};

struct alert_data {
    uint8_t  severity;
    char     rule[MAX_NAME_LEN];
    char     detail[MAX_MSG_LEN];
};

struct trace_data {
    char     trace_id[MAX_TRACE_ID_LEN];
    char     span_id[MAX_TRACE_ID_LEN];
    char     parent_id[MAX_TRACE_ID_LEN];
    char     operation[MAX_NAME_LEN];
    uint64_t duration_us;
    uint8_t  status;
};

struct audit_data {
    char     user[MAX_NAME_LEN];
    char     action[MAX_NAME_LEN];
    char     resource[MAX_RESOURCE_LEN];
    uint8_t  outcome;
};

/* Parsed record */
typedef struct {
    struct rec_header header;
    union {
        struct metric_data metric;
        struct log_data    log;
        struct alert_data  alert;
        struct trace_data  trace;
        struct audit_data  audit;
    } data;
} record_t;

/* ---- Public API ---- */

int rec_parse(const uint8_t *buf, size_t len, record_t *out, rec_error_t *err);
int rec_validate(const record_t *rec, rec_error_t *err);
int rec_format(const record_t *rec, char *buf, size_t buf_len);
size_t rec_serialize(const record_t *rec, uint8_t *buf, size_t buf_len,
                     rec_error_t *err);
uint32_t rec_crc32(const uint8_t *data, size_t len);

#endif /* RECORD_H */
"""

RECORD_INTERNAL_H = r"""/*
 * record_internal.h - Internal helpers shared across modules
 */

#ifndef RECORD_INTERNAL_H
#define RECORD_INTERNAL_H

#include "record.h"
#include <stdio.h>

/* Timestamp validation bounds (microseconds) */
#define MIN_TIMESTAMP 1000000000000000ULL
#define MAX_TIMESTAMP 99999999999999999ULL

/* Payload sizes for each record type */
#define METRIC_PAYLOAD_SIZE  80
#define LOG_PAYLOAD_SIZE    321
#define ALERT_PAYLOAD_SIZE  321
#define TRACE_PAYLOAD_SIZE  169
#define AUDIT_PAYLOAD_SIZE  257

/* Set error context */
static inline void set_error(rec_error_t *err, int code, const char *msg) {
    if (err) {
        err->code = code;
        snprintf(err->message, sizeof(err->message), "%s", msg);
    }
}

/* Clear error context */
static inline void clear_error(rec_error_t *err) {
    if (err) {
        err->code = REC_OK;
        err->message[0] = '\0';
    }
}

/* Validate timestamp range.  Returns 0 if valid, -1 otherwise. */
static inline int validate_timestamp(uint64_t ts) {
    return (ts >= MIN_TIMESTAMP && ts <= MAX_TIMESTAMP) ? 0 : -1;
}

/* Get payload size for a record type.  Returns 0 for unknown. */
static inline size_t payload_size_for_type(uint8_t type) {
    switch (type) {
        case REC_METRIC: return METRIC_PAYLOAD_SIZE;
        case REC_LOG:    return LOG_PAYLOAD_SIZE;
        case REC_ALERT:  return ALERT_PAYLOAD_SIZE;
        case REC_TRACE:  return TRACE_PAYLOAD_SIZE;
        case REC_AUDIT:  return AUDIT_PAYLOAD_SIZE;
        default:         return 0;
    }
}

#endif /* RECORD_INTERNAL_H */
"""

CHECKSUM_C = r"""/*
 * checksum.c - CRC32 implementation with precomputed const table
 */

#include "record.h"
#include <stdint.h>

/* CRC_TABLE */

uint32_t rec_crc32(const uint8_t *data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc = crc_table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFFu;
}
"""

PARSER_C = r"""/*
 * parser.c - Record parsing from binary wire format
 */

#include "record.h"
#include "record_internal.h"
#include <string.h>

int rec_parse(const uint8_t *buf, size_t len, record_t *out, rec_error_t *err) {
    if (!buf || !out) {
        set_error(err, REC_ERR_NULL, "null argument to rec_parse");
        return REC_ERR_NULL;
    }

    memset(out, 0, sizeof(*out));

    if (len < REC_HDR_SIZE) {
        set_error(err, REC_ERR_SHORT, "buffer too short for header");
        return REC_ERR_SHORT;
    }

    /* Parse header */
    memcpy(&out->header.magic, buf + 0, 2);
    out->header.version = buf[2];
    out->header.type = buf[3];
    memcpy(&out->header.payload_len, buf + 4, 4);
    memcpy(&out->header.timestamp_us, buf + 8, 8);
    memcpy(&out->header.crc32, buf + 16, 4);

    if (out->header.magic != REC_MAGIC) {
        set_error(err, REC_ERR_MAGIC, "bad magic number");
        return REC_ERR_MAGIC;
    }
    if (out->header.version != REC_VERSION) {
        set_error(err, REC_ERR_MAGIC, "unsupported version");
        return REC_ERR_MAGIC;
    }
    if (len < REC_HDR_SIZE + out->header.payload_len) {
        set_error(err, REC_ERR_SHORT, "buffer too short for payload");
        return REC_ERR_SHORT;
    }

    const uint8_t *payload = buf + REC_HDR_SIZE;
    uint32_t plen = out->header.payload_len;

    /* CRC32 verification */
    uint32_t computed = rec_crc32(payload, plen);
    if (computed != out->header.crc32) {
        set_error(err, REC_ERR_CRC, "CRC32 mismatch");
        return REC_ERR_CRC;
    }

    /* Timestamp validation (shared helper) */
    if (validate_timestamp(out->header.timestamp_us) != 0) {
        set_error(err, REC_ERR_RANGE, "timestamp out of range");
        return REC_ERR_RANGE;
    }

    /* Check payload size */
    size_t expected = payload_size_for_type(out->header.type);
    if (expected == 0) {
        set_error(err, REC_ERR_TYPE, "unknown record type");
        return REC_ERR_TYPE;
    }
    if (plen < expected) {
        set_error(err, REC_ERR_SHORT, "payload too short for type");
        return REC_ERR_SHORT;
    }

    /* Parse payload by type */
    switch (out->header.type) {
        case REC_METRIC:
            memcpy(out->data.metric.name, payload, 64);
            memcpy(&out->data.metric.value, payload + 64, 8);
            memcpy(&out->data.metric.sample_time, payload + 72, 8);
            if (validate_timestamp(out->data.metric.sample_time) != 0) {
                set_error(err, REC_ERR_RANGE, "metric sample_time out of range");
                return REC_ERR_RANGE;
            }
            break;
        case REC_LOG:
            out->data.log.level = payload[0];
            memcpy(out->data.log.source, payload + 1, 64);
            memcpy(out->data.log.message, payload + 65, 256);
            if (out->data.log.level > 4) {
                set_error(err, REC_ERR_RANGE, "invalid log level");
                return REC_ERR_RANGE;
            }
            break;
        case REC_ALERT:
            out->data.alert.severity = payload[0];
            memcpy(out->data.alert.rule, payload + 1, 64);
            memcpy(out->data.alert.detail, payload + 65, 256);
            if (out->data.alert.severity < 1 || out->data.alert.severity > 5) {
                set_error(err, REC_ERR_RANGE, "invalid alert severity");
                return REC_ERR_RANGE;
            }
            break;
        case REC_TRACE:
            memcpy(out->data.trace.trace_id, payload, 32);
            memcpy(out->data.trace.span_id, payload + 32, 32);
            memcpy(out->data.trace.parent_id, payload + 64, 32);
            memcpy(out->data.trace.operation, payload + 96, 64);
            memcpy(&out->data.trace.duration_us, payload + 160, 8);
            out->data.trace.status = payload[168];
            break;
        case REC_AUDIT:
            memcpy(out->data.audit.user, payload, 64);
            memcpy(out->data.audit.action, payload + 64, 64);
            memcpy(out->data.audit.resource, payload + 128, 128);
            out->data.audit.outcome = payload[256];
            break;
    }

    clear_error(err);
    return REC_OK;
}
"""

VALIDATOR_C = r"""/*
 * validator.c - Record validation
 */

#include "record.h"
#include "record_internal.h"

int rec_validate(const record_t *rec, rec_error_t *err) {
    if (!rec) {
        set_error(err, REC_ERR_NULL, "null record");
        return REC_ERR_NULL;
    }
    if (rec->header.magic != REC_MAGIC) {
        set_error(err, REC_ERR_MAGIC, "invalid magic");
        return REC_ERR_MAGIC;
    }
    if (rec->header.version != REC_VERSION) {
        set_error(err, REC_ERR_MAGIC, "bad version");
        return REC_ERR_MAGIC;
    }
    if (validate_timestamp(rec->header.timestamp_us) != 0) {
        set_error(err, REC_ERR_RANGE, "timestamp out of range");
        return REC_ERR_RANGE;
    }

    switch (rec->header.type) {
        case REC_METRIC:
            if (validate_timestamp(rec->data.metric.sample_time) != 0) {
                set_error(err, REC_ERR_RANGE, "metric sample_time out of range");
                return REC_ERR_RANGE;
            }
            break;
        case REC_LOG:
            if (rec->data.log.level > 4) {
                set_error(err, REC_ERR_RANGE, "invalid log level");
                return REC_ERR_RANGE;
            }
            break;
        case REC_ALERT:
            if (rec->data.alert.severity < 1 || rec->data.alert.severity > 5) {
                set_error(err, REC_ERR_RANGE, "invalid alert severity");
                return REC_ERR_RANGE;
            }
            break;
        case REC_TRACE:
        case REC_AUDIT:
            break;
        default:
            set_error(err, REC_ERR_TYPE, "unknown record type");
            return REC_ERR_TYPE;
    }

    clear_error(err);
    return REC_OK;
}
"""

FORMATTER_C = r"""/*
 * formatter.c - Human-readable record formatting (thread-safe)
 */

#include "record.h"
#include "record_internal.h"
#include <stdio.h>

int rec_format(const record_t *rec, char *buf, size_t buf_len) {
    if (!rec || !buf || buf_len == 0)
        return -1;

    int n = 0;
    switch (rec->header.type) {
        case REC_METRIC:
            n = snprintf(buf, buf_len,
                "METRIC: name=%.64s value=%.6f sample_time=%llu ts=%llu",
                rec->data.metric.name, rec->data.metric.value,
                (unsigned long long)rec->data.metric.sample_time,
                (unsigned long long)rec->header.timestamp_us);
            break;
        case REC_LOG:
            n = snprintf(buf, buf_len,
                "LOG: level=%u source=%.64s message=%.256s ts=%llu",
                rec->data.log.level, rec->data.log.source,
                rec->data.log.message,
                (unsigned long long)rec->header.timestamp_us);
            break;
        case REC_ALERT:
            n = snprintf(buf, buf_len,
                "ALERT: severity=%u rule=%.64s detail=%.256s ts=%llu",
                rec->data.alert.severity, rec->data.alert.rule,
                rec->data.alert.detail,
                (unsigned long long)rec->header.timestamp_us);
            break;
        case REC_TRACE:
            n = snprintf(buf, buf_len,
                "TRACE: trace=%.32s span=%.32s parent=%.32s op=%.64s "
                "dur=%llu status=%u ts=%llu",
                rec->data.trace.trace_id, rec->data.trace.span_id,
                rec->data.trace.parent_id, rec->data.trace.operation,
                (unsigned long long)rec->data.trace.duration_us,
                rec->data.trace.status,
                (unsigned long long)rec->header.timestamp_us);
            break;
        case REC_AUDIT:
            n = snprintf(buf, buf_len,
                "AUDIT: user=%.64s action=%.64s resource=%.128s "
                "outcome=%u ts=%llu",
                rec->data.audit.user, rec->data.audit.action,
                rec->data.audit.resource, rec->data.audit.outcome,
                (unsigned long long)rec->header.timestamp_us);
            break;
        default:
            n = snprintf(buf, buf_len, "UNKNOWN: type=%u", rec->header.type);
            break;
    }
    return n;
}
"""

SERIALIZER_C = r"""/*
 * serializer.c - Record serialization to binary wire format
 */

#include "record.h"
#include "record_internal.h"
#include <string.h>

size_t rec_serialize(const record_t *rec, uint8_t *buf, size_t buf_len,
                     rec_error_t *err) {
    if (!rec || !buf) {
        set_error(err, REC_ERR_NULL, "null argument to rec_serialize");
        return 0;
    }

    size_t psize = payload_size_for_type(rec->header.type);
    if (psize == 0) {
        set_error(err, REC_ERR_TYPE, "unknown type in serialize");
        return 0;
    }

    size_t total = REC_HDR_SIZE + psize;
    if (buf_len < total) {
        set_error(err, REC_ERR_SHORT, "output buffer too small");
        return 0;
    }

    /* Build payload */
    uint8_t payload[512];
    memset(payload, 0, sizeof(payload));

    switch (rec->header.type) {
        case REC_METRIC:
            memcpy(payload, rec->data.metric.name, 64);
            memcpy(payload + 64, &rec->data.metric.value, 8);
            memcpy(payload + 72, &rec->data.metric.sample_time, 8);
            break;
        case REC_LOG:
            payload[0] = rec->data.log.level;
            memcpy(payload + 1, rec->data.log.source, 64);
            memcpy(payload + 65, rec->data.log.message, 256);
            break;
        case REC_ALERT:
            payload[0] = rec->data.alert.severity;
            memcpy(payload + 1, rec->data.alert.rule, 64);
            memcpy(payload + 65, rec->data.alert.detail, 256);
            break;
        case REC_TRACE:
            memcpy(payload, rec->data.trace.trace_id, 32);
            memcpy(payload + 32, rec->data.trace.span_id, 32);
            memcpy(payload + 64, rec->data.trace.parent_id, 32);
            memcpy(payload + 96, rec->data.trace.operation, 64);
            memcpy(payload + 160, &rec->data.trace.duration_us, 8);
            payload[168] = rec->data.trace.status;
            break;
        case REC_AUDIT:
            memcpy(payload, rec->data.audit.user, 64);
            memcpy(payload + 64, rec->data.audit.action, 64);
            memcpy(payload + 128, rec->data.audit.resource, 128);
            payload[256] = rec->data.audit.outcome;
            break;
    }

    /* CRC32 of payload (single shared implementation) */
    uint32_t crc = rec_crc32(payload, psize);

    /* Write header */
    uint16_t magic = REC_MAGIC;
    uint8_t version = REC_VERSION;
    uint8_t type = rec->header.type;
    uint32_t plen = (uint32_t)psize;
    uint64_t ts = rec->header.timestamp_us;

    memcpy(buf + 0, &magic, 2);
    buf[2] = version;
    buf[3] = type;
    memcpy(buf + 4, &plen, 4);
    memcpy(buf + 8, &ts, 8);
    memcpy(buf + 16, &crc, 4);

    /* Write payload */
    memcpy(buf + REC_HDR_SIZE, payload, psize);

    clear_error(err);
    return total;
}
"""

MAKEFILE = """CC = gcc
CFLAGS = -Wall -Wextra -O2
AR = ar
ARFLAGS = rcs

SRCS = checksum.c parser.c validator.c formatter.c serializer.c
OBJS = $(SRCS:.c=.o)
LIB = librecord.a

all: $(LIB) main

$(LIB): $(OBJS)
\t$(AR) $(ARFLAGS) $@ $^

main: main.c $(LIB)
\t$(CC) $(CFLAGS) -o $@ $< -L. -lrecord

%.o: %.c record.h record_internal.h
\t$(CC) $(CFLAGS) -c $< -o $@

clean:
\trm -f *.o $(LIB) main

.PHONY: all clean
"""

MAIN_C = r"""/*
 * main.c - Example usage of the refactored record processing library
 */

#include "record.h"
#include <stdio.h>
#include <string.h>

int main(void) {
    record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_METRIC;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.metric.name, "cpu.usage", sizeof(rec.data.metric.name));
    rec.data.metric.value = 42.5;
    rec.data.metric.sample_time = 1700000000000000ULL;

    uint8_t buf[1024];
    rec_error_t err;
    memset(&err, 0, sizeof(err));

    size_t n = rec_serialize(&rec, buf, sizeof(buf), &err);
    if (n == 0) {
        fprintf(stderr, "serialize failed: %s\n", err.message);
        return 1;
    }
    printf("Serialized %zu bytes\n", n);

    record_t parsed;
    memset(&err, 0, sizeof(err));
    int ret = rec_parse(buf, n, &parsed, &err);
    if (ret != 0) {
        fprintf(stderr, "parse failed: %s\n", err.message);
        return 1;
    }

    char fmt[512];
    rec_format(&parsed, fmt, sizeof(fmt));
    printf("Parsed: %s\n", fmt);

    return 0;
}
"""


if __name__ == "__main__":
    main()
