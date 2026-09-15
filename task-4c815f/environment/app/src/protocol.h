#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <stdint.h>

#define CMD_STORE_DATA      0x01
#define CMD_LOG_EVENT       0x02
#define CMD_MANAGE_SESSION  0x03
#define CMD_CLEANUP_TXN     0x04
#define CMD_BATCH_ALLOC     0x05
#define CMD_PROCESS_PACKET  0x06
#define CMD_READ_CONFIG     0x07

#define SUBCMD_SESSION_CREATE  0x01
#define SUBCMD_SESSION_STATS   0x02
#define SUBCMD_SESSION_RESET   0x03

#define SUBCMD_TXN_BEGIN    0x01
#define SUBCMD_TXN_COMMIT   0x02
#define SUBCMD_TXN_ROLLBACK 0x03

typedef struct __attribute__((packed)) {
    uint8_t  command_id;
    uint8_t  subcommand;
    uint16_t flags;
    uint32_t payload_length;
} request_header_t;

#define MAX_PAYLOAD_SIZE 4096

#endif
