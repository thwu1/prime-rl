/*
 * vdriver - Virtual device driver command processor
 *
 * Reads binary command files and dispatches them through
 * handler functions, simulating a kernel IOCTL dispatch table.
 */

#include "handlers.h"
#include "pool.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int dispatch_command(const request_header_t *hdr, const uint8_t *payload) {
    switch (hdr->command_id) {
        case CMD_STORE_DATA:      return handle_store_data(hdr, payload);
        case CMD_LOG_EVENT:       return handle_log_event(hdr, payload);
        case CMD_MANAGE_SESSION:  return handle_manage_session(hdr, payload);
        case CMD_CLEANUP_TXN:     return handle_cleanup_txn(hdr, payload);
        case CMD_BATCH_ALLOC:     return handle_batch_alloc(hdr, payload);
        case CMD_PROCESS_PACKET:  return handle_process_packet(hdr, payload);
        case CMD_READ_CONFIG:     return handle_read_config(hdr, payload);
        default:
            fprintf(stderr, "[dispatch] unknown command: 0x%02x\n", hdr->command_id);
            return -1;
    }
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <command_file>\n", argv[0]);
        return 1;
    }

    FILE *fp = fopen(argv[1], "rb");
    if (!fp) {
        perror("fopen");
        return 1;
    }

    handlers_init();

    uint8_t payload_buf[MAX_PAYLOAD_SIZE];
    request_header_t hdr;
    int cmd_count = 0;

    while (fread(&hdr, sizeof(hdr), 1, fp) == 1) {
        cmd_count++;

        if (hdr.payload_length > MAX_PAYLOAD_SIZE) {
            fprintf(stderr, "[main] payload too large: %u (max %d)\n",
                    hdr.payload_length, MAX_PAYLOAD_SIZE);
            fseek(fp, hdr.payload_length, SEEK_CUR);
            continue;
        }

        if (hdr.payload_length > 0) {
            size_t rd = fread(payload_buf, 1, hdr.payload_length, fp);
            if (rd != hdr.payload_length) {
                fprintf(stderr, "[main] short read: got %zu expected %u\n",
                        rd, hdr.payload_length);
                break;
            }
        }

        fprintf(stderr, "[main] cmd #%d: id=0x%02x sub=0x%02x flags=0x%04x len=%u\n",
                cmd_count, hdr.command_id, hdr.subcommand, hdr.flags,
                hdr.payload_length);

        int result = dispatch_command(&hdr, payload_buf);
        if (result != 0) {
            fprintf(stderr, "[main] command 0x%02x returned error\n",
                    hdr.command_id);
        }
    }

    fprintf(stderr, "[main] processed %d commands\n", cmd_count);
    handlers_shutdown();
    pool_dump_stats();

    fclose(fp);
    return 0;
}
