/*
 * scs_parse - ARM Cortex-M System Control Space dump parser
 *
 * Reads CMEX v1 binary dump files and prints decoded register state
 * in human-readable format. Useful for inspecting exception state
 * snapshots during debugging.
 *
 * Build: make -C /app/tools
 * Usage: /app/tools/scs_parse <dump_file.bin>
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define HEADER_SIZE 8
#define RECORD_SIZE 192

static const char *exc_name(uint8_t num) {
    switch (num) {
        case 1:  return "Reset";
        case 2:  return "NMI";
        case 3:  return "HardFault";
        case 4:  return "MemManage";
        case 5:  return "BusFault";
        case 6:  return "UsageFault";
        case 10: return "DebugMonitor";
        case 11: return "SVCall";
        case 14: return "PendSV";
        case 15: return "SysTick";
        default: {
            static char buf[16];
            if (num >= 16) {
                snprintf(buf, sizeof(buf), "IRQ%d", num - 16);
                return buf;
            }
            snprintf(buf, sizeof(buf), "Reserved(%d)", num);
            return buf;
        }
    }
}

static const char *query_name(uint8_t qt) {
    switch (qt) {
        case 1: return "execution_priority";
        case 2: return "pending_exception";
        case 3: return "fault_target";
        case 4: return "exc_return_valid";
        case 5: return "stack_frame_size";
        case 6: return "wfi_wakeup";
        default: return "unknown";
    }
}

static const char *fault_type_name(uint8_t idx) {
    static const char *names[] = {
        "UndefInstr", "InvState", "InvPC", "NoCP",
        "DAccViol", "IAccViol", "MUnstkErr", "MStkErr",
        "PreciseDataBusError", "ImpreciseDataBusError", "IBusErr",
        "UnstkErr", "StkErr"
    };
    if (idx < 13) return names[idx];
    return "unknown";
}

static uint32_t read_u32_le(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <dump_file.bin>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror("fopen");
        return 1;
    }

    uint8_t header[HEADER_SIZE];
    if (fread(header, 1, HEADER_SIZE, f) != HEADER_SIZE) {
        fprintf(stderr, "Error: truncated header\n");
        fclose(f);
        return 1;
    }

    if (memcmp(header, "CMEX", 4) != 0) {
        fprintf(stderr, "Error: invalid magic (expected CMEX)\n");
        fclose(f);
        return 1;
    }

    uint8_t version = header[4];
    uint16_t num_records = header[6] | ((uint16_t)header[7] << 8);
    printf("CMEX v%d — %d record(s)\n\n", version, num_records);

    uint8_t rec[RECORD_SIZE];
    for (int i = 0; i < num_records; i++) {
        if (fread(rec, 1, RECORD_SIZE, f) != RECORD_SIZE) {
            fprintf(stderr, "Error: truncated record %d\n", i);
            break;
        }

        char id[33] = {0};
        memcpy(id, rec, 32);

        uint32_t aircr = read_u32_le(rec + 0x20);
        uint32_t shpr1 = read_u32_le(rec + 0x24);
        uint32_t shpr2 = read_u32_le(rec + 0x28);
        uint32_t shpr3 = read_u32_le(rec + 0x2C);

        /* Extract PRIGROUP from AIRCR bits [10:8] */
        int prigroup = (aircr >> 7) & 0x7;

        uint8_t basepri   = rec[0x30];
        uint8_t primask   = rec[0x31];
        uint8_t faultmask = rec[0x32];
        uint8_t control   = rec[0x33];
        uint8_t arch      = rec[0x99];
        uint8_t query_type = rec[0x9A];

        printf("[%d] %s\n", i, id);
        printf("  Arch: ARMv%d-M\n", arch);
        printf("  AIRCR=0x%08X  PRIGROUP=%d\n", aircr, prigroup);
        printf("  SHPR1=0x%08X  SHPR2=0x%08X  SHPR3=0x%08X\n",
               shpr1, shpr2, shpr3);

        /* Decode SHPR priorities */
        printf("  System handler priorities:\n");
        printf("    MemManage=%d  BusFault=%d  UsageFault=%d\n",
               (shpr1 >> 0) & 0xFF, (shpr1 >> 8) & 0xFF, (shpr1 >> 16) & 0xFF);
        printf("    DebugMon=%d  SVCall=%d\n",
               (shpr2 >> 16) & 0xFF, (shpr2 >> 24) & 0xFF);
        printf("    PendSV=%d  SysTick=%d\n",
               (shpr3 >> 16) & 0xFF, (shpr3 >> 24) & 0xFF);

        printf("  BASEPRI=%d  PRIMASK=%d  FAULTMASK=%d  CONTROL=0x%02X",
               basepri, primask, faultmask, control);
        if (control & 0x04) printf(" [FPCA]");
        printf("\n");

        /* Active exceptions */
        int num_active = rec[0x74];
        printf("  Active exceptions (%d):", num_active);
        for (int j = 0; j < num_active && j < 8; j++) {
            uint8_t en = rec[0x75 + j * 2];
            int8_t  pr = (int8_t)rec[0x76 + j * 2];
            printf("  %s(pri=%d)", exc_name(en), pr);
        }
        printf("\n");

        /* Pending exceptions */
        int num_pending = rec[0x85];
        printf("  Pending exceptions (%d):", num_pending);
        for (int j = 0; j < num_pending && j < 8; j++) {
            uint8_t en = rec[0x86 + j * 2];
            int8_t  pr = (int8_t)rec[0x87 + j * 2];
            printf("  %s(pri=%d)", exc_name(en), pr);
        }
        printf("\n");

        /* Fault enables */
        printf("  Fault enables: UsageFault=%d  BusFault=%d  MemManage=%d\n",
               rec[0x96], rec[0x97], rec[0x98]);

        /* Query */
        printf("  Query: %s", query_name(query_type));
        if (query_type == 3) {
            printf("  fault_type=%s", fault_type_name(rec[0x9B]));
        } else if (query_type == 4) {
            uint32_t er = read_u32_le(rec + 0x9B);
            printf("  exc_return=0x%08X", er);
        }
        printf("\n\n");
    }

    fclose(f);
    return 0;
}
