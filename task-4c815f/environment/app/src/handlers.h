#ifndef HANDLERS_H
#define HANDLERS_H

#include "protocol.h"
#include <stdint.h>
#include <stddef.h>

/* Storage entry for CMD_STORE_DATA */
#define STORE_BUFFER_SIZE 128

typedef struct {
    uint32_t entry_id;
    uint32_t data_len;
    uint8_t  data[STORE_BUFFER_SIZE];
    uint32_t checksum;
} store_entry_t;

/* Log levels for CMD_LOG_EVENT */
#define LOG_INFO  0
#define LOG_WARN  1
#define LOG_ERROR 2

#define MAX_LOG_PREFIX    256
#define LOG_ENTRY_BUFFER   64

typedef struct __attribute__((packed)) {
    uint8_t  level;
    uint8_t  facility;
    uint16_t msg_len;
    char     message[];
} log_event_t;

/* Session management for CMD_MANAGE_SESSION */
typedef struct {
    uint32_t session_id;
    uint32_t created_at;
    uint64_t bytes_in;
    uint64_t bytes_out;
    uint32_t request_count;
    uint8_t  active;
} session_stats_t;

typedef struct session_ctx {
    uint32_t        id;
    session_stats_t *stats;
    void            *priv_data;
    uint8_t          state;   /* 0=inactive, 1=active, 2=suspended */
} session_ctx_t;

/* Transaction for CMD_CLEANUP_TXN */
typedef struct {
    uint32_t  txn_id;
    uint8_t  *data_buf;
    size_t    data_len;
    uint8_t   committed;
    void    (*cleanup_fn)(void *);
} transaction_t;

/* Batch allocation for CMD_BATCH_ALLOC */
typedef struct __attribute__((packed)) {
    uint32_t count;
    uint32_t item_size;
    uint8_t  fill_value;
    uint8_t  reserved[3];
} batch_request_t;

/* Packet processing for CMD_PROCESS_PACKET */
typedef struct {
    uint32_t src_addr;
    uint32_t dst_addr;
    uint16_t src_port;
    uint16_t dst_port;
} net_header_t;

typedef struct {
    uint32_t object_id;
    union {
        uint32_t packet_type;
        void   (*process_cb)(void *, size_t);
    } handler;
    uint8_t  priority;
    uint8_t  reserved[3];
} packet_object_t;

/* Config for CMD_READ_CONFIG */
#define CONFIG_MAX_ENTRIES 16

typedef struct {
    char     key[32];
    char     value[64];
    uint32_t flags;
} config_entry_t;

typedef struct {
    uint32_t       entry_count;
    config_entry_t entries[CONFIG_MAX_ENTRIES];
} config_store_t;

/* Handler function declarations */
int handle_store_data(const request_header_t *hdr, const uint8_t *payload);
int handle_log_event(const request_header_t *hdr, const uint8_t *payload);
int handle_manage_session(const request_header_t *hdr, const uint8_t *payload);
int handle_cleanup_txn(const request_header_t *hdr, const uint8_t *payload);
int handle_batch_alloc(const request_header_t *hdr, const uint8_t *payload);
int handle_process_packet(const request_header_t *hdr, const uint8_t *payload);
int handle_read_config(const request_header_t *hdr, const uint8_t *payload);

void handlers_init(void);
void handlers_shutdown(void);

#endif
