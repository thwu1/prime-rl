/*
 * record.h - Binary record processing library
 *
 * Parses, validates, formats, and serializes five binary record types
 * used in a distributed telemetry pipeline.
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
#define REC_ERR_NULL    -1
#define REC_ERR_SHORT   -2
#define REC_ERR_MAGIC   -3
#define REC_ERR_CRC     -4
#define REC_ERR_TYPE    -5
#define REC_ERR_ALLOC   -6
#define REC_ERR_RANGE   -7

/* Protocol constants */
#define REC_MAGIC       0xABCD
#define REC_VERSION     1
#define REC_HDR_SIZE    20

/* Maximum sizes */
#define MAX_NAME_LEN        64
#define MAX_MSG_LEN         256
#define MAX_TRACE_ID_LEN    32
#define MAX_RESOURCE_LEN    128
#define MAX_ERROR_MSG_LEN   256

/* Timestamp validation bounds */
#define MIN_TIMESTAMP 1000000000000000ULL
#define MAX_TIMESTAMP 99999999999999999ULL

/*
 * Record header - 20 bytes, little-endian wire format:
 *   [0:2]   uint16 magic
 *   [2]     uint8  version
 *   [3]     uint8  type
 *   [4:8]   uint32 payload_len
 *   [8:16]  uint64 timestamp_us
 *   [16:20] uint32 crc32 (of payload bytes)
 */
struct rec_header {
    uint16_t magic;
    uint8_t  version;
    uint8_t  type;
    uint32_t payload_len;
    uint64_t timestamp_us;
    uint32_t crc32;
};

/* Payload structures (binary layout uses field-by-field memcpy) */

struct metric_data {
    char     name[MAX_NAME_LEN];    /* offset 0,  64 bytes */
    double   value;                 /* offset 64,  8 bytes */
    uint64_t sample_time;           /* offset 72,  8 bytes */
};                                  /* total: 80 bytes */

struct log_data {
    uint8_t  level;                 /* offset 0,   1 byte  (0=DBG,1=INF,2=WRN,3=ERR,4=FTL) */
    char     source[MAX_NAME_LEN];  /* offset 1,  64 bytes */
    char     message[MAX_MSG_LEN];  /* offset 65, 256 bytes */
};                                  /* total: 321 bytes */

struct alert_data {
    uint8_t  severity;              /* offset 0,   1 byte (1-5) */
    char     rule[MAX_NAME_LEN];    /* offset 1,  64 bytes */
    char     detail[MAX_MSG_LEN];   /* offset 65, 256 bytes */
};                                  /* total: 321 bytes */

struct trace_data {
    char     trace_id[MAX_TRACE_ID_LEN];   /* offset 0,   32 bytes */
    char     span_id[MAX_TRACE_ID_LEN];    /* offset 32,  32 bytes */
    char     parent_id[MAX_TRACE_ID_LEN];  /* offset 64,  32 bytes */
    char     operation[MAX_NAME_LEN];      /* offset 96,  64 bytes */
    uint64_t duration_us;                  /* offset 160,  8 bytes */
    uint8_t  status;                       /* offset 168,  1 byte (0=ok,1=err) */
};                                         /* total: 169 bytes */

struct audit_data {
    char     user[MAX_NAME_LEN];           /* offset 0,   64 bytes */
    char     action[MAX_NAME_LEN];         /* offset 64,  64 bytes */
    char     resource[MAX_RESOURCE_LEN];   /* offset 128, 128 bytes */
    uint8_t  outcome;                      /* offset 256,  1 byte (0=deny,1=allow) */
};                                         /* total: 257 bytes */

/* Parsed record: header + type-specific payload */
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

/* Global error state */
extern int g_rec_errno;
extern char g_rec_errmsg[MAX_ERROR_MSG_LEN];

/* ---- Public API ---- */

/* Parse a binary record from buf into out.  Sets g_rec_errno on failure. */
void rec_parse(const uint8_t *buf, size_t len, record_t *out);

/* Validate an already-parsed record.  Sets g_rec_errno on failure. */
void rec_validate(const record_t *rec);

/* Format record to human-readable string.  Returns pointer to internal
 * static buffer -- NOT thread-safe. */
char *rec_format(const record_t *rec);

/* Serialize a record to binary.  Returns bytes written, or 0 on error. */
size_t rec_serialize(const record_t *rec, uint8_t *buf, size_t buf_len);

/* Retrieve last error information */
const char *rec_strerror(void);
int rec_errno(void);

/* Compute CRC32 (polynomial 0xEDB88320, reflected) */
uint32_t rec_crc32(const uint8_t *data, size_t len);

#endif /* RECORD_H */
