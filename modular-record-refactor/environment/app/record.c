/*
 * record.c - Monolithic implementation of the binary record processing library
 */

#include "record.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* ------------------------------------------------------------------ */
/* Global error state                                                  */
/* ------------------------------------------------------------------ */

int g_rec_errno = 0;
char g_rec_errmsg[MAX_ERROR_MSG_LEN] = {0};

static void set_error(int code, const char *msg) {
    g_rec_errno = code;
    snprintf(g_rec_errmsg, sizeof(g_rec_errmsg), "%s", msg);
}

/* ------------------------------------------------------------------ */
/* CRC32 implementation                                                */
/* ------------------------------------------------------------------ */

static uint32_t crc_table[256];
static int crc_table_ready = 0;

static void ensure_crc_table(void) {
    if (crc_table_ready) return;
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int j = 0; j < 8; j++) {
            c = (c & 1) ? ((c >> 1) ^ 0xEDB88320u) : (c >> 1);
        }
        crc_table[i] = c;
    }
    crc_table_ready = 1;
}

uint32_t rec_crc32(const uint8_t *data, size_t len) {
    ensure_crc_table();
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc = crc_table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFFu;
}

/* Duplicated CRC helper for serialization verification */
static uint32_t compute_payload_crc(const uint8_t *data, size_t len) {
    ensure_crc_table();
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc = crc_table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFFu;
}

/* ------------------------------------------------------------------ */
/* Parse                                                               */
/* ------------------------------------------------------------------ */

void rec_parse(const uint8_t *buf, size_t len, record_t *out) {
    if (!buf || !out) {
        set_error(REC_ERR_NULL, "null argument to rec_parse");
        return;
    }

    memset(out, 0, sizeof(*out));

    if (len < REC_HDR_SIZE) {
        set_error(REC_ERR_SHORT, "buffer too short for header");
        return;
    }

    /* Parse header fields (little-endian, field by field) */
    memcpy(&out->header.magic, buf + 0, 2);
    out->header.version = buf[2];
    out->header.type = buf[3];
    memcpy(&out->header.payload_len, buf + 4, 4);
    memcpy(&out->header.timestamp_us, buf + 8, 8);
    memcpy(&out->header.crc32, buf + 16, 4);

    if (out->header.magic != REC_MAGIC) {
        set_error(REC_ERR_MAGIC, "bad magic number");
        return;
    }
    if (out->header.version != REC_VERSION) {
        set_error(REC_ERR_MAGIC, "unsupported version");
        return;
    }
    if (len < REC_HDR_SIZE + out->header.payload_len) {
        set_error(REC_ERR_SHORT, "buffer too short for payload");
        return;
    }

    const uint8_t *payload = buf + REC_HDR_SIZE;
    uint32_t plen = out->header.payload_len;

    /* Verify CRC32 of payload */
    uint32_t computed = rec_crc32(payload, plen);
    if (computed != out->header.crc32) {
        set_error(REC_ERR_CRC, "CRC32 mismatch");
        return;
    }

    /* Timestamp validation */
    if (out->header.timestamp_us < MIN_TIMESTAMP ||
        out->header.timestamp_us > MAX_TIMESTAMP) {
        set_error(REC_ERR_RANGE, "timestamp out of range");
        return;
    }

    /* Dispatch by type */
    switch (out->header.type) {
        case REC_METRIC: {
            if (plen < 80) {
                set_error(REC_ERR_SHORT, "metric payload too short");
                return;
            }
            memcpy(out->data.metric.name, payload, 64);
            memcpy(&out->data.metric.value, payload + 64, 8);
            memcpy(&out->data.metric.sample_time, payload + 72, 8);
            /* Duplicated timestamp check */
            if (out->data.metric.sample_time < MIN_TIMESTAMP ||
                out->data.metric.sample_time > MAX_TIMESTAMP) {
                set_error(REC_ERR_RANGE, "metric sample_time out of range");
                return;
            }
            break;
        }
        case REC_LOG: {
            if (plen < 321) {
                set_error(REC_ERR_SHORT, "log payload too short");
                return;
            }
            out->data.log.level = payload[0];
            memcpy(out->data.log.source, payload + 1, 64);
            memcpy(out->data.log.message, payload + 65, 256);
            if (out->data.log.level > 4) {
                set_error(REC_ERR_RANGE, "invalid log level");
                return;
            }
            break;
        }
        case REC_ALERT: {
            if (plen < 321) {
                set_error(REC_ERR_SHORT, "alert payload too short");
                return;
            }
            out->data.alert.severity = payload[0];
            memcpy(out->data.alert.rule, payload + 1, 64);
            memcpy(out->data.alert.detail, payload + 65, 256);
            if (out->data.alert.severity < 1 || out->data.alert.severity > 5) {
                set_error(REC_ERR_RANGE, "invalid alert severity");
                return;
            }
            break;
        }
        case REC_TRACE: {
            if (plen < 169) {
                set_error(REC_ERR_SHORT, "trace payload too short");
                return;
            }
            memcpy(out->data.trace.trace_id, payload, 32);
            memcpy(out->data.trace.span_id, payload + 32, 32);
            memcpy(out->data.trace.parent_id, payload + 64, 32);
            memcpy(out->data.trace.operation, payload + 96, 64);
            memcpy(&out->data.trace.duration_us, payload + 160, 8);
            out->data.trace.status = payload[168];
            break;
        }
        case REC_AUDIT: {
            if (plen < 257) {
                set_error(REC_ERR_SHORT, "audit payload too short");
                return;
            }
            memcpy(out->data.audit.user, payload, 64);
            memcpy(out->data.audit.action, payload + 64, 64);
            memcpy(out->data.audit.resource, payload + 128, 128);
            out->data.audit.outcome = payload[256];
            break;
        }
        default:
            set_error(REC_ERR_TYPE, "unknown record type");
            return;
    }

    g_rec_errno = REC_OK;
}

/* ------------------------------------------------------------------ */
/* Validate                                                            */
/* ------------------------------------------------------------------ */

void rec_validate(const record_t *rec) {
    if (!rec) {
        set_error(REC_ERR_NULL, "null record");
        return;
    }
    if (rec->header.magic != REC_MAGIC) {
        set_error(REC_ERR_MAGIC, "invalid magic");
        return;
    }
    if (rec->header.version != REC_VERSION) {
        set_error(REC_ERR_MAGIC, "bad version");
        return;
    }
    /* Duplicated timestamp check */
    if (rec->header.timestamp_us < MIN_TIMESTAMP ||
        rec->header.timestamp_us > MAX_TIMESTAMP) {
        set_error(REC_ERR_RANGE, "timestamp out of range");
        return;
    }
    switch (rec->header.type) {
        case REC_METRIC:
            if (rec->data.metric.sample_time < MIN_TIMESTAMP ||
                rec->data.metric.sample_time > MAX_TIMESTAMP) {
                set_error(REC_ERR_RANGE, "metric sample_time out of range");
                return;
            }
            break;
        case REC_LOG:
            if (rec->data.log.level > 4) {
                set_error(REC_ERR_RANGE, "invalid log level");
                return;
            }
            break;
        case REC_ALERT:
            if (rec->data.alert.severity < 1 || rec->data.alert.severity > 5) {
                set_error(REC_ERR_RANGE, "invalid alert severity");
                return;
            }
            break;
        case REC_TRACE:
        case REC_AUDIT:
            break;
        default:
            set_error(REC_ERR_TYPE, "unknown record type");
            return;
    }
    g_rec_errno = REC_OK;
}

/* ------------------------------------------------------------------ */
/* Format (uses static buffer -- not thread-safe)                      */
/* ------------------------------------------------------------------ */

static char fmt_buf[1024];

char *rec_format(const record_t *rec) {
    if (!rec) {
        set_error(REC_ERR_NULL, "null record");
        return NULL;
    }
    switch (rec->header.type) {
        case REC_METRIC:
            snprintf(fmt_buf, sizeof(fmt_buf),
                "METRIC: name=%.64s value=%.6f sample_time=%llu ts=%llu",
                rec->data.metric.name, rec->data.metric.value,
                (unsigned long long)rec->data.metric.sample_time,
                (unsigned long long)rec->header.timestamp_us);
            break;
        case REC_LOG:
            snprintf(fmt_buf, sizeof(fmt_buf),
                "LOG: level=%u source=%.64s message=%.256s ts=%llu",
                rec->data.log.level, rec->data.log.source,
                rec->data.log.message,
                (unsigned long long)rec->header.timestamp_us);
            break;
        case REC_ALERT:
            snprintf(fmt_buf, sizeof(fmt_buf),
                "ALERT: severity=%u rule=%.64s detail=%.256s ts=%llu",
                rec->data.alert.severity, rec->data.alert.rule,
                rec->data.alert.detail,
                (unsigned long long)rec->header.timestamp_us);
            break;
        case REC_TRACE:
            snprintf(fmt_buf, sizeof(fmt_buf),
                "TRACE: trace=%.32s span=%.32s parent=%.32s op=%.64s "
                "dur=%llu status=%u ts=%llu",
                rec->data.trace.trace_id, rec->data.trace.span_id,
                rec->data.trace.parent_id, rec->data.trace.operation,
                (unsigned long long)rec->data.trace.duration_us,
                rec->data.trace.status,
                (unsigned long long)rec->header.timestamp_us);
            break;
        case REC_AUDIT:
            snprintf(fmt_buf, sizeof(fmt_buf),
                "AUDIT: user=%.64s action=%.64s resource=%.128s "
                "outcome=%u ts=%llu",
                rec->data.audit.user, rec->data.audit.action,
                rec->data.audit.resource, rec->data.audit.outcome,
                (unsigned long long)rec->header.timestamp_us);
            break;
        default:
            snprintf(fmt_buf, sizeof(fmt_buf),
                "UNKNOWN: type=%u", rec->header.type);
            break;
    }
    return fmt_buf;
}

/* ------------------------------------------------------------------ */
/* Serialize                                                           */
/* ------------------------------------------------------------------ */

size_t rec_serialize(const record_t *rec, uint8_t *buf, size_t buf_len) {
    if (!rec || !buf) {
        set_error(REC_ERR_NULL, "null argument to rec_serialize");
        return 0;
    }

    size_t payload_size = 0;
    switch (rec->header.type) {
        case REC_METRIC: payload_size = 80;  break;
        case REC_LOG:    payload_size = 321; break;
        case REC_ALERT:  payload_size = 321; break;
        case REC_TRACE:  payload_size = 169; break;
        case REC_AUDIT:  payload_size = 257; break;
        default:
            set_error(REC_ERR_TYPE, "unknown type in serialize");
            return 0;
    }

    size_t total = REC_HDR_SIZE + payload_size;
    if (buf_len < total) {
        set_error(REC_ERR_SHORT, "output buffer too small");
        return 0;
    }

    /* Build payload into temp buffer */
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

    /* Compute CRC using duplicated helper */
    uint32_t crc = compute_payload_crc(payload, payload_size);

    /* Write header */
    uint16_t magic = REC_MAGIC;
    uint8_t version = REC_VERSION;
    uint8_t type = rec->header.type;
    uint32_t plen = (uint32_t)payload_size;
    uint64_t ts = rec->header.timestamp_us;

    memcpy(buf + 0, &magic, 2);
    buf[2] = version;
    buf[3] = type;
    memcpy(buf + 4, &plen, 4);
    memcpy(buf + 8, &ts, 8);
    memcpy(buf + 16, &crc, 4);

    /* Write payload */
    memcpy(buf + REC_HDR_SIZE, payload, payload_size);

    return total;
}

/* ------------------------------------------------------------------ */
/* Error accessors                                                     */
/* ------------------------------------------------------------------ */

const char *rec_strerror(void) {
    return g_rec_errmsg;
}

int rec_errno(void) {
    return g_rec_errno;
}
