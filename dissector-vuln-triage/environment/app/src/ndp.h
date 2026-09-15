#ifndef NDP_H
#define NDP_H

#include <stdint.h>
#include <stddef.h>

/*
 * Network Diagnostic Protocol (NDP) Packet Format
 *
 * Header (12 bytes):
 *   [0-3]   magic        uint32_be  0x4E445001
 *   [4]     type         uint8      packet type
 *   [5]     flags        uint8      bit flags
 *   [6-7]   payload_len  uint16_be  payload length (bytes after header)
 *   [8-11]  checksum     uint32_be  CRC32 of payload
 *
 * Payload (variable):
 *   Type-specific data following the header.
 *
 * Packet Types:
 *   0x01 PROBE  - Echo probe (simple connectivity check)
 *   0x02 IDENT  - Interface identification with extensions
 *   0x03 AUTH   - Authentication handshake
 *   0x04 BULK   - Bulk data transfer with block operations
 *   0x05 DIAG   - Diagnostic command
 *
 * IDENT Extension Format (6-byte header + variable data):
 *   [0-1]  class_num    uint16_be
 *   [2]    c_type       uint8
 *   [3]    reserved     uint8 (must be 0)
 *   [4-5]  ext_length   uint16_be (total length including this 6-byte header)
 *
 *   Known extensions (class 0x0002):
 *     c_type=0x01  Interface Index    (4 bytes: uint32_be)
 *     c_type=0x02  Interface Name     (variable: printable ASCII)
 *     c_type=0x03  IPv4 Address       (4 bytes: a.b.c.d)
 *
 * AUTH Payload:
 *   [0]     phase       uint8 (0x01=INIT, 0x02=RESPONSE, 0x03=CONFIRM)
 *   Phase-specific fields follow.
 *
 *   INIT:
 *     [1-2]   user_len   uint16_be
 *     [3..]   username   variable
 *     [3+user_len, +2]  token_len  uint16_be (optional)
 *     [5+user_len..]    token      variable  (hex chars)
 *
 * BULK Payload:
 *   [0-1]  num_blocks   uint16_be
 *   [2-3]  reserved     uint16_be
 *   Blocks follow sequentially:
 *     [0-1]  block_type  uint16_be (0x0001=APPEND, 0x0002=OVERWRITE, 0x0003=FINALIZE)
 *     [2-3]  block_len   uint16_be (length of block data after this 4-byte header)
 *     [4..]  block_data  variable
 *
 *   OVERWRITE block_data:
 *     [0-3]  write_offset  uint32_be  (offset in output buffer)
 *     [4..]  data           variable   (bytes to write)
 *
 * DIAG Payload:
 *   [0]     command     uint8 (0x01=STATUS, 0x02=RESET, 0x03=QUERY)
 *   [1-2]   arg_len     uint16_be
 *   [3..]   argument    variable (printable ASCII)
 */

#define NDP_MAGIC         0x4E445001
#define NDP_HEADER_SIZE   12

/* Packet types */
#define NDP_PROBE         0x01
#define NDP_IDENT         0x02
#define NDP_AUTH          0x03
#define NDP_BULK          0x04
#define NDP_DIAG          0x05

/* Flags */
#define NDP_FLAG_DEBUG    0x01
#define NDP_FLAG_VERBOSE  0x02
#define NDP_FLAG_COMPRESS 0x04

/* IDENT extension definitions */
#define IDENT_EXT_HEADER_SIZE  6
#define IDENT_CLASS_IFACE      0x0002
#define IDENT_CTYPE_INDEX      0x01
#define IDENT_CTYPE_NAME       0x02
#define IDENT_CTYPE_ADDR4      0x03

/* AUTH sub-types */
#define AUTH_PHASE_INIT     0x01
#define AUTH_PHASE_RESPONSE 0x02
#define AUTH_PHASE_CONFIRM  0x03

/* BULK block types */
#define BULK_APPEND    0x0001
#define BULK_OVERWRITE 0x0002
#define BULK_FINALIZE  0x0003

/* DIAG command types */
#define DIAG_CMD_STATUS  0x01
#define DIAG_CMD_RESET   0x02
#define DIAG_CMD_QUERY   0x03

/* Buffer sizes */
#define IDENT_NAME_BUF    128
#define AUTH_USER_BUF     256
#define AUTH_TOKEN_BUF    128
#define DIAG_CMD_BUF       64
#define LOG_BUF_SIZE      512

/* Read big-endian values from buffer */
static inline uint16_t read_u16_be(const uint8_t *p) {
    return ((uint16_t)p[0] << 8) | p[1];
}

static inline uint32_t read_u32_be(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8)  | p[3];
}

/* Handler function prototypes */
int handle_probe(const uint8_t *payload, size_t len, uint8_t flags);
int handle_ident(const uint8_t *payload, size_t len, uint8_t flags);
int handle_auth(const uint8_t *payload, size_t len, uint8_t flags);
int handle_bulk(const uint8_t *payload, size_t len, uint8_t flags);
int handle_diag(const uint8_t *payload, size_t len, uint8_t flags);

/* Utility functions */
uint32_t ndp_crc32(const uint8_t *data, size_t len);

#endif /* NDP_H */
