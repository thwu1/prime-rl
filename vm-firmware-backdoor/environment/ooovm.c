/*
 * ooovm - OOO Virtual Machine Interpreter
 * Field Code Architecture v3.7
 *
 * Binary format:
 *   [0:4]  Magic: "OOOV"
 *   [4:6]  Version (uint16 LE)
 *   [6:8]  Entry point (uint16 LE, offset into code segment)
 *   [8:]   Code/data segment (loaded at memory address 0)
 *
 * Usage: ./ooovm <firmware.bin>
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#define MSIZ  0x10000
#define DSIZ  1024
#define RSIZ  256

/* Field Code instruction set - operation identifiers */
#define FC_NUL 0x00
#define FC_LI8 0x01
#define FC_LI16 0x02
#define FC_DRP 0x03
#define FC_CPY 0x04
#define FC_SWP 0x05
#define FC_INC 0x06
#define FC_DEC 0x07
#define FC_AD2 0x08
#define FC_SB2 0x09
#define FC_ML2 0x0A
#define FC_DV2 0x0B
#define FC_RM2 0x0C
#define FC_AN2 0x0D
#define FC_OR2 0x0E
#define FC_XR2 0x0F
#define FC_NT1 0x10
#define FC_SL2 0x11
#define FC_SR2 0x12
#define FC_TEQ 0x13
#define FC_TLT 0x14
#define FC_TGT 0x15
#define FC_JMA 0x16
#define FC_JZA 0x17
#define FC_JNA 0x18
#define FC_CLA 0x19
#define FC_RBK 0x1A
#define FC_LDM 0x1B
#define FC_STM 0x1C
#define FC_RDI 0x1D
#define FC_WRO 0x1E
#define FC_HLT 0x1F
#define FC_OVR 0x20

static uint8_t  mem[MSIZ];
static uint16_t ds[DSIZ];    /* data stack */
static uint16_t rs[RSIZ];    /* return stack */
static int dp = 0, rp = 0;

static inline void dpush(uint16_t v) { if (dp < DSIZ) ds[dp++] = v; }
static inline uint16_t dpop(void) { return dp > 0 ? ds[--dp] : 0; }
static inline uint16_t dpeek(void) { return dp > 0 ? ds[dp-1] : 0; }
static inline void rpush(uint16_t v) { if (rp < RSIZ) rs[rp++] = v; }
static inline uint16_t rpop(void) { return rp > 0 ? rs[--rp] : 0; }

static inline uint16_t r16(uint16_t a) {
    return (uint16_t)mem[a] | ((uint16_t)mem[a + 1] << 8);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <firmware>\n", argv[0]);
        return 1;
    }

    FILE *fp = fopen(argv[1], "rb");
    if (!fp) { perror(argv[1]); return 1; }

    uint8_t hdr[8];
    if (fread(hdr, 1, 8, fp) != 8 || memcmp(hdr, "OOOV", 4)) {
        fprintf(stderr, "invalid firmware\n");
        return 1;
    }

    uint16_t entry = (uint16_t)hdr[6] | ((uint16_t)hdr[7] << 8);
    fread(mem, 1, MSIZ, fp);
    fclose(fp);

    uint16_t pc = entry;
    uint16_t a, b, t;
    int run = 1;

    while (run) {
        uint8_t op = mem[pc++];
        switch (op) {
        case FC_NUL: break;
        case FC_LI8: dpush(mem[pc++]); break;
        case FC_LI16: dpush(r16(pc)); pc += 2; break;
        case FC_DRP: dpop(); break;
        case FC_CPY: dpush(dpeek()); break;
        case FC_SWP: a = dpop(); b = dpop(); dpush(a); dpush(b); break;
        case FC_INC: dpush(dpop() + 1); break;
        case FC_DEC: dpush(dpop() - 1); break;
        case FC_AD2: b = dpop(); a = dpop(); dpush(a + b); break;
        case FC_SB2: b = dpop(); a = dpop(); dpush(a - b); break;
        case FC_ML2: b = dpop(); a = dpop(); dpush(a * b); break;
        case FC_DV2: b = dpop(); a = dpop(); dpush(b ? a / b : 0); break;
        case FC_RM2: b = dpop(); a = dpop(); dpush(b ? a % b : 0); break;
        case FC_AN2: b = dpop(); a = dpop(); dpush(a & b); break;
        case FC_OR2: b = dpop(); a = dpop(); dpush(a | b); break;
        case FC_XR2: b = dpop(); a = dpop(); dpush(a ^ b); break;
        case FC_NT1: dpush(~dpop()); break;
        case FC_SL2: b = dpop(); a = dpop(); dpush(a << b); break;
        case FC_SR2: b = dpop(); a = dpop(); dpush(a >> b); break;
        case FC_TEQ: b = dpop(); a = dpop(); dpush(a == b ? 1 : 0); break;
        case FC_TLT: b = dpop(); a = dpop(); dpush(a < b ? 1 : 0); break;
        case FC_TGT: b = dpop(); a = dpop(); dpush(a > b ? 1 : 0); break;
        case FC_JMA: pc = r16(pc); break;
        case FC_JZA: t = r16(pc); pc += 2; if (dpop() == 0) pc = t; break;
        case FC_JNA: t = r16(pc); pc += 2; if (dpop() != 0) pc = t; break;
        case FC_CLA: t = r16(pc); pc += 2; rpush(pc); pc = t; break;
        case FC_RBK: pc = rpop(); break;
        case FC_LDM: dpush(mem[dpop()]); break;
        case FC_STM: t = dpop(); mem[t] = (uint8_t)(dpop() & 0xFF); break;
        case FC_RDI: { int c = getchar(); dpush(c == EOF ? 0xFFFF : (uint16_t)c); } break;
        case FC_WRO: putchar(dpop() & 0xFF); fflush(stdout); break;
        case FC_HLT: run = 0; break;
        case FC_OVR: if (dp >= 2) dpush(ds[dp - 2]); break;
        default:
            fprintf(stderr, "bad opcode 0x%02x @%04x\n", op, pc - 1);
            run = 0;
        }
    }
    return 0;
}
