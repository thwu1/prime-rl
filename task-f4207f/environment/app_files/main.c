/* main.c — Driver for 6502 emulator; runs a binary and reports result */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cpu6502.h"

#define MAX_INSTRUCTIONS 200000000  /* safety limit */

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr,
            "Usage: %s <binary> <load_addr_hex> [entry_addr_hex] [--cycles] [--success ADDR]\n",
            argv[0]);
        return 1;
    }

    const char *binfile = argv[1];
    uint16_t load_addr = (uint16_t)strtol(argv[2], NULL, 16);
    uint16_t entry_addr = load_addr;
    int report_cycles = 0;
    uint16_t success_addr = 0;
    int have_success = 0;

    /* Parse positional entry address (arg 3 if not a flag) */
    if (argc >= 4 && argv[3][0] != '-')
        entry_addr = (uint16_t)strtol(argv[3], NULL, 16);

    /* Parse flags */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--cycles") == 0)
            report_cycles = 1;
        if (strcmp(argv[i], "--success") == 0 && i + 1 < argc) {
            success_addr = (uint16_t)strtol(argv[i + 1], NULL, 16);
            have_success = 1;
            i++;
        }
    }

    FILE *f = fopen(binfile, "rb");
    if (!f) { perror("fopen"); return 1; }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);

    cpu6502_t cpu;
    cpu_init(&cpu);

    if (load_addr + size > 65536) {
        fprintf(stderr, "Binary too large for address space\n");
        fclose(f);
        return 1;
    }
    fread(&cpu.memory[load_addr], 1, size, f);
    fclose(f);

    cpu.PC = entry_addr;

    unsigned long long total_cycles = 0;
    unsigned long long instr_count = 0;

    for (unsigned long long i = 0; i < MAX_INSTRUCTIONS; i++) {
        uint16_t pc_before = cpu.PC;
        int cycles = cpu_step(&cpu);
        total_cycles += cycles;
        instr_count++;

        /* Detect trap: PC unchanged after instruction */
        if (cpu.PC == pc_before) {
            if (report_cycles)
                printf("cycles=%llu instructions=%llu\n", total_cycles, instr_count);
            printf("TRAP at $%04X\n", cpu.PC);
            if (have_success) {
                if (cpu.PC == success_addr) {
                    printf("SUCCESS\n");
                    return 0;
                } else {
                    printf("FAIL: stuck at $%04X (expected $%04X)\n",
                           cpu.PC, success_addr);
                    return 1;
                }
            }
            /* No --success: just report the trap */
            return 0;
        }
    }

    printf("TIMEOUT: exceeded %d instructions\n", MAX_INSTRUCTIONS);
    return 1;
}
