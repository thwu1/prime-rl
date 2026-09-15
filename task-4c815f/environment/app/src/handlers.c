#include "handlers.h"
#include "pool.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

/* ---- Global driver state ---- */
static session_ctx_t  *g_current_session = NULL;
static transaction_t  *g_current_txn     = NULL;
static config_store_t  g_config;
static uint32_t g_next_entry_id   = 1;
static uint32_t g_next_session_id = 1;
static uint32_t g_next_txn_id     = 1;

void handlers_init(void) {
    memset(&g_config, 0, sizeof(g_config));
    g_config.entry_count = 4;
    strncpy(g_config.entries[0].key,   "max_connections", 31);
    strncpy(g_config.entries[0].value, "1024",            63);
    g_config.entries[0].flags = 0x01;
    strncpy(g_config.entries[1].key,   "timeout_ms",      31);
    strncpy(g_config.entries[1].value, "30000",           63);
    g_config.entries[1].flags = 0x01;
    strncpy(g_config.entries[2].key,   "log_level",       31);
    strncpy(g_config.entries[2].value, "INFO",            63);
    g_config.entries[2].flags = 0x03;
    strncpy(g_config.entries[3].key,   "pool_size",       31);
    strncpy(g_config.entries[3].value, "8192",            63);
    g_config.entries[3].flags = 0x01;
}

void handlers_shutdown(void) {
    if (g_current_session) {
        if (g_current_session->stats)
            pool_free(g_current_session->stats, POOL_TAG('S','s','t','a'));
        pool_free(g_current_session, POOL_TAG('S','e','s','s'));
        g_current_session = NULL;
    }
    if (g_current_txn) {
        if (g_current_txn->data_buf)
            pool_free(g_current_txn->data_buf, POOL_TAG('T','d','a','t'));
        pool_free(g_current_txn, POOL_TAG('T','x','n','s'));
        g_current_txn = NULL;
    }
}

/* ================================================================
 * CMD_STORE_DATA handler
 * Stores user-provided data entries in pool-allocated storage.
 * Payload layout: [4-byte user ID] [variable-length data]
 * ================================================================ */

static uint32_t compute_checksum(const uint8_t *data, size_t len) {
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++)
        sum = ((sum << 5) + sum) + data[i];
    return sum;
}

int handle_store_data(const request_header_t *hdr, const uint8_t *payload) {
    if (hdr->payload_length < sizeof(uint32_t)) {
        fprintf(stderr, "[store] invalid payload size\n");
        return -1;
    }

    store_entry_t *entry = (store_entry_t *)pool_alloc(
        POOL_NONPAGED, sizeof(store_entry_t), POOL_TAG('S','t','o','r'));
    if (!entry) {
        fprintf(stderr, "[store] allocation failed\n");
        return -1;
    }

    entry->entry_id = g_next_entry_id++;

    /* Extract data portion after the 4-byte user ID field */
    uint32_t data_offset = sizeof(uint32_t);
    uint32_t data_len = hdr->payload_length - data_offset;

    entry->data_len = data_len;
    memcpy(entry->data, payload + data_offset, data_len);

    entry->checksum = compute_checksum(entry->data, data_len);

    fprintf(stderr, "[store] entry %u: %u bytes cksum=0x%08x\n",
            entry->entry_id, data_len, entry->checksum);

    pool_free(entry, POOL_TAG('S','t','o','r'));
    return 0;
}

/* ================================================================
 * CMD_LOG_EVENT handler
 * Formats and logs events with a severity-level prefix.
 * ================================================================ */

static const char *log_level_str(uint8_t level) {
    switch (level) {
        case LOG_INFO:  return "INFO";
        case LOG_WARN:  return "WARN";
        case LOG_ERROR: return "ERROR";
        default:        return "UNKNOWN";
    }
}

static int format_log_entry(const char *prefix, const char *message,
                            uint16_t msg_len, char *output, size_t output_size) {
    int written = snprintf(output, output_size, "[%s] ", prefix);
    if (written < 0) return -1;

    memcpy(output + written, message, msg_len);
    output[written + msg_len] = '\0';
    return written + msg_len;
}

int handle_log_event(const request_header_t *hdr, const uint8_t *payload) {
    if (hdr->payload_length < sizeof(log_event_t)) {
        fprintf(stderr, "[log] payload too small\n");
        return -1;
    }

    const log_event_t *evt = (const log_event_t *)payload;

    /* Validate message length against maximum prefix capacity */
    if (evt->msg_len > MAX_LOG_PREFIX) {
        fprintf(stderr, "[log] message too long: %u\n", evt->msg_len);
        return -1;
    }

    if (hdr->payload_length < sizeof(log_event_t) + evt->msg_len) {
        fprintf(stderr, "[log] payload length mismatch\n");
        return -1;
    }

    char formatted[LOG_ENTRY_BUFFER];
    const char *level = log_level_str(evt->level);

    int result = format_log_entry(level, evt->message, evt->msg_len,
                                  formatted, sizeof(formatted));
    if (result < 0) {
        fprintf(stderr, "[log] format error\n");
        return -1;
    }

    fprintf(stderr, "[log] %s\n", formatted);
    return 0;
}

/* ================================================================
 * CMD_MANAGE_SESSION handler
 * Manages session lifecycle: create, query stats, reset.
 * ================================================================ */

static session_ctx_t *create_session(void) {
    session_ctx_t *ctx = (session_ctx_t *)pool_alloc(
        POOL_NONPAGED, sizeof(session_ctx_t), POOL_TAG('S','e','s','s'));
    if (!ctx) return NULL;

    ctx->id    = g_next_session_id++;
    ctx->state = 1; /* active */

    ctx->stats = (session_stats_t *)pool_alloc(
        POOL_NONPAGED, sizeof(session_stats_t), POOL_TAG('S','s','t','a'));
    if (!ctx->stats) {
        pool_free(ctx, POOL_TAG('S','e','s','s'));
        return NULL;
    }

    ctx->stats->session_id = ctx->id;
    ctx->stats->created_at = 0;
    ctx->stats->active     = 1;
    return ctx;
}

static void release_session_resources(session_ctx_t *ctx) {
    if (ctx->priv_data) {
        pool_free(ctx->priv_data, POOL_TAG('S','p','r','v'));
        ctx->priv_data = NULL;
    }
    if (ctx->stats) {
        pool_free(ctx->stats, POOL_TAG('S','s','t','a'));
    }
}

int handle_manage_session(const request_header_t *hdr, const uint8_t *payload) {
    (void)payload;

    switch (hdr->subcommand) {
        case SUBCMD_SESSION_CREATE: {
            if (g_current_session) {
                fprintf(stderr, "[session] already exists\n");
                return -1;
            }
            g_current_session = create_session();
            if (!g_current_session) {
                fprintf(stderr, "[session] creation failed\n");
                return -1;
            }
            fprintf(stderr, "[session] created id=%u\n", g_current_session->id);
            return 0;
        }

        case SUBCMD_SESSION_RESET: {
            if (!g_current_session) {
                fprintf(stderr, "[session] no active session\n");
                return -1;
            }
            fprintf(stderr, "[session] resetting id=%u\n", g_current_session->id);
            release_session_resources(g_current_session);
            g_current_session->state = 2;  /* suspended */
            return 0;
        }

        case SUBCMD_SESSION_STATS: {
            if (!g_current_session) {
                fprintf(stderr, "[session] no active session\n");
                return -1;
            }
            if (g_current_session->state == 0) {
                fprintf(stderr, "[session] inactive\n");
                return -1;
            }

            session_stats_t *s = g_current_session->stats;
            fprintf(stderr, "[session] id=%u in=%lu out=%lu reqs=%u active=%u\n",
                    s->session_id, s->bytes_in, s->bytes_out,
                    s->request_count, s->active);
            return 0;
        }

        default:
            fprintf(stderr, "[session] unknown subcmd 0x%02x\n", hdr->subcommand);
            return -1;
    }
}

/* ================================================================
 * CMD_CLEANUP_TXN handler
 * Transaction management with commit/rollback semantics.
 * Rollback invokes registered cleanup callbacks.
 * ================================================================ */

static void txn_cleanup_callback(void *arg) {
    transaction_t *txn = (transaction_t *)arg;
    if (txn->data_buf) {
        fprintf(stderr, "[txn] cleanup: releasing data buffer\n");
        pool_free(txn->data_buf, POOL_TAG('T','d','a','t'));
        txn->data_buf = NULL;
    }
}

int handle_cleanup_txn(const request_header_t *hdr, const uint8_t *payload) {
    switch (hdr->subcommand) {
        case SUBCMD_TXN_BEGIN: {
            if (g_current_txn) {
                fprintf(stderr, "[txn] already in progress\n");
                return -1;
            }

            g_current_txn = (transaction_t *)pool_alloc(
                POOL_NONPAGED, sizeof(transaction_t), POOL_TAG('T','x','n','s'));
            if (!g_current_txn) return -1;

            g_current_txn->txn_id     = g_next_txn_id++;
            g_current_txn->committed  = 0;
            g_current_txn->cleanup_fn = txn_cleanup_callback;

            size_t buf_size = hdr->payload_length > 0 ? hdr->payload_length : 256;
            g_current_txn->data_buf = (uint8_t *)pool_alloc(
                POOL_PAGED, buf_size, POOL_TAG('T','d','a','t'));
            if (!g_current_txn->data_buf) {
                pool_free(g_current_txn, POOL_TAG('T','x','n','s'));
                g_current_txn = NULL;
                return -1;
            }
            g_current_txn->data_len = buf_size;

            if (hdr->payload_length > 0)
                memcpy(g_current_txn->data_buf, payload, hdr->payload_length);

            fprintf(stderr, "[txn] begin id=%u (%zu bytes)\n",
                    g_current_txn->txn_id, buf_size);
            return 0;
        }

        case SUBCMD_TXN_COMMIT: {
            if (!g_current_txn) {
                fprintf(stderr, "[txn] no active transaction\n");
                return -1;
            }
            g_current_txn->committed = 1;
            fprintf(stderr, "[txn] committed id=%u\n", g_current_txn->txn_id);

            if (g_current_txn->data_buf) {
                pool_free(g_current_txn->data_buf, POOL_TAG('T','d','a','t'));
                g_current_txn->data_buf = NULL;
            }
            pool_free(g_current_txn, POOL_TAG('T','x','n','s'));
            g_current_txn = NULL;
            return 0;
        }

        case SUBCMD_TXN_ROLLBACK: {
            if (!g_current_txn) {
                fprintf(stderr, "[txn] no active transaction\n");
                return -1;
            }
            fprintf(stderr, "[txn] rollback id=%u\n", g_current_txn->txn_id);

            /* Release the data buffer */
            if (g_current_txn->data_buf) {
                pool_free(g_current_txn->data_buf, POOL_TAG('T','d','a','t'));
            }

            /* Run registered cleanup handler */
            if (g_current_txn->cleanup_fn) {
                g_current_txn->cleanup_fn(g_current_txn);
            }

            pool_free(g_current_txn, POOL_TAG('T','x','n','s'));
            g_current_txn = NULL;
            return 0;
        }

        default:
            fprintf(stderr, "[txn] unknown subcmd 0x%02x\n", hdr->subcommand);
            return -1;
    }
}

/* ================================================================
 * CMD_BATCH_ALLOC handler
 * Batch memory allocation for multiple fixed-size items.
 * Copies item data from the tail of the payload.
 * ================================================================ */

#define BATCH_HEADER_SIZE 16

int handle_batch_alloc(const request_header_t *hdr, const uint8_t *payload) {
    if (hdr->payload_length < sizeof(batch_request_t)) {
        fprintf(stderr, "[batch] invalid payload\n");
        return -1;
    }

    const batch_request_t *req = (const batch_request_t *)payload;

    if (req->count == 0 || req->item_size == 0) {
        fprintf(stderr, "[batch] invalid count/size\n");
        return -1;
    }

    /* Calculate total allocation size */
    uint32_t total_data = req->count * req->item_size;
    uint32_t alloc_size = total_data + BATCH_HEADER_SIZE;

    fprintf(stderr, "[batch] count=%u item_size=%u total=%u alloc=%u\n",
            req->count, req->item_size, total_data, alloc_size);

    uint8_t *buffer = (uint8_t *)pool_alloc(
        POOL_PAGED, alloc_size, POOL_TAG('B','a','t','c'));
    if (!buffer) {
        fprintf(stderr, "[batch] allocation failed\n");
        return -1;
    }

    /* Write batch metadata header */
    memcpy(buffer,      &req->count,     sizeof(uint32_t));
    memcpy(buffer + 4,  &req->item_size, sizeof(uint32_t));
    *(uint32_t *)(buffer + 8)  = total_data;
    *(uint32_t *)(buffer + 12) = alloc_size;

    /* Copy item data from payload tail */
    size_t items_offset = sizeof(batch_request_t);
    if (hdr->payload_length > items_offset) {
        size_t copy_len = hdr->payload_length - items_offset;
        memcpy(buffer + BATCH_HEADER_SIZE, payload + items_offset, copy_len);
    }

    fprintf(stderr, "[batch] allocated %u items\n", req->count);
    pool_free(buffer, POOL_TAG('B','a','t','c'));
    return 0;
}

/* ================================================================
 * CMD_PROCESS_PACKET handler
 * Network packet processing with callback dispatch.
 * High-priority packets with the custom-handler flag invoke
 * the registered processing callback.
 * ================================================================ */

static void default_packet_handler(void *data, size_t len) {
    fprintf(stderr, "[packet] default handler: %zu bytes\n", len);
    (void)data;
}

int handle_process_packet(const request_header_t *hdr, const uint8_t *payload) {
    if (hdr->payload_length < sizeof(net_header_t) + sizeof(uint32_t)) {
        fprintf(stderr, "[packet] payload too small\n");
        return -1;
    }

    const net_header_t *net = (const net_header_t *)payload;

    packet_object_t *pkt = (packet_object_t *)pool_alloc(
        POOL_NONPAGED, sizeof(packet_object_t), POOL_TAG('P','k','t','o'));
    if (!pkt) return -1;

    pkt->object_id = net->src_addr ^ net->dst_addr;

    /* Set up processing callback when custom-handler flag is present */
    if (hdr->flags & 0x01) {
        pkt->handler.process_cb = default_packet_handler;
    }

    /* Record the packet type from the user-supplied header extension */
    uint32_t user_packet_type;
    memcpy(&user_packet_type, payload + sizeof(net_header_t), sizeof(uint32_t));
    pkt->handler.packet_type = user_packet_type;
    pkt->priority = (uint8_t)(hdr->flags >> 8);

    fprintf(stderr, "[packet] obj=0x%08x type=%u pri=%u\n",
            pkt->object_id, pkt->handler.packet_type, pkt->priority);

    /* High-priority packets with custom flag get callback processing */
    if (pkt->priority > 0 && (hdr->flags & 0x01)) {
        const uint8_t *pkt_data = payload + sizeof(net_header_t) + sizeof(uint32_t);
        size_t pkt_data_len = hdr->payload_length
                            - sizeof(net_header_t) - sizeof(uint32_t);
        pkt->handler.process_cb((void *)pkt_data, pkt_data_len);
    }

    pool_free(pkt, POOL_TAG('P','k','t','o'));
    return 0;
}

/* ================================================================
 * CMD_READ_CONFIG handler
 * Read/write configuration entries by index.
 * ================================================================ */

typedef struct __attribute__((packed)) {
    uint32_t index;
    uint8_t  operation;   /* 0 = read, 1 = write */
    uint8_t  _pad[3];
    char     new_value[64];
} config_request_t;

int handle_read_config(const request_header_t *hdr, const uint8_t *payload) {
    if (hdr->payload_length < sizeof(config_request_t)) {
        fprintf(stderr, "[config] invalid payload\n");
        return -1;
    }

    const config_request_t *req = (const config_request_t *)payload;

    config_entry_t *target = &g_config.entries[req->index];

    if (req->operation == 0) {
        fprintf(stderr, "[config] read [%u]: key='%s' value='%s' flags=0x%x\n",
                req->index, target->key, target->value, target->flags);
    } else if (req->operation == 1) {
        memcpy(target->value, req->new_value, sizeof(target->value));
        fprintf(stderr, "[config] write [%u]: key='%s' -> '%s'\n",
                req->index, target->key, target->value);
    } else {
        fprintf(stderr, "[config] unknown op: %u\n", req->operation);
        return -1;
    }

    return 0;
}
