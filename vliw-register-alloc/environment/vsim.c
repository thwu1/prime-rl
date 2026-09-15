/*
 * vsim - VLIW Cycle-Accurate Simulator
 *
 *
 * Reads a .vbin text file describing a compiled VLIW program and simulates
 * it cycle-accurately, respecting functional-unit latencies and pipeline stalls.
 *
 * Usage: vsim <input.vbin> [--trace]
 *
 * .vbin interchange format:
 *   REGS <num_phys_regs>
 *   DATASIZE <data_size>
 *   INIT <addr> <value>        (one line per non-zero memory word)
 *   BUNDLE
 *   <slot> <op> <dst> <src0> <src1> <src2> <imm>
 *   <slot> nop                 (inactive slot)
 *   ENDBUNDLE
 *   ...
 *   END
 *
 * Slot names: alu0, alu1, mul, mem
 * Ops: add sub and or xor shl shr slt mov li mul muladd lw sw
 *
 * Output (stdout):
 *   CYCLES <total_cycles>
 *   MEM <addr> <value>         (one line per address 0..data_size-1)
 *   STATUS OK
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define MAX_REGS 512
#define MEM_SIZE 256
#define MAX_BUNDLES 10000
#define SLOTS_PER_BUNDLE 4

typedef struct {
    char op[16];
    int dst;
    int srcs[3];
    uint32_t imm;
    int active;
} Slot;

typedef struct {
    Slot slots[SLOTS_PER_BUNDLE];
} Bundle;

static int num_regs = 0;
static int data_size = 0;
static uint32_t mem[MEM_SIZE];
static uint32_t regs[MAX_REGS];
static int ready_at[MAX_REGS];
static Bundle bundles[MAX_BUNDLES];
static int num_bundles = 0;

static int get_latency(const char *op) {
    if (strcmp(op, "mul") == 0 || strcmp(op, "muladd") == 0) return 3;
    if (strcmp(op, "lw") == 0) return 4;
    return 1;  /* all ALU ops and sw */
}

static uint32_t exec_op(const char *op, uint32_t a, uint32_t b, uint32_t c,
                        uint32_t imm) {
    if (strcmp(op, "add") == 0)    return a + b;
    if (strcmp(op, "sub") == 0)    return a - b;
    if (strcmp(op, "and") == 0)    return a & b;
    if (strcmp(op, "or") == 0)     return a | b;
    if (strcmp(op, "xor") == 0)    return a ^ b;
    if (strcmp(op, "shl") == 0)    return a << (b & 31);
    if (strcmp(op, "shr") == 0)    return a >> (b & 31);
    if (strcmp(op, "slt") == 0)    return (a < b) ? 1u : 0u;
    if (strcmp(op, "mov") == 0)    return a;
    if (strcmp(op, "li") == 0)     return imm;
    if (strcmp(op, "mul") == 0)    return a * b;
    if (strcmp(op, "muladd") == 0) return a * b + c;
    fprintf(stderr, "vsim: unknown op '%s'\n", op);
    exit(2);
}

static int parse_vbin(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "vsim: cannot open '%s'\n", path);
        return 1;
    }

    char line[512];
    int in_bundle = 0;

    memset(mem, 0, sizeof(mem));
    num_bundles = 0;

    while (fgets(line, sizeof(line), f)) {
        char *nl = strchr(line, '\n');
        if (nl) *nl = 0;
        nl = strchr(line, '\r');
        if (nl) *nl = 0;

        if (line[0] == '#' || line[0] == '\0') continue;

        if (strncmp(line, "REGS ", 5) == 0) {
            num_regs = atoi(line + 5);
            if (num_regs > MAX_REGS) {
                fprintf(stderr, "vsim: too many regs (%d > %d)\n",
                        num_regs, MAX_REGS);
                fclose(f);
                return 1;
            }
        } else if (strncmp(line, "DATASIZE ", 9) == 0) {
            data_size = atoi(line + 9);
        } else if (strncmp(line, "INIT ", 5) == 0) {
            unsigned addr, val;
            if (sscanf(line + 5, "%u %u", &addr, &val) == 2
                && addr < MEM_SIZE) {
                mem[addr] = (uint32_t)val;
            }
        } else if (strcmp(line, "BUNDLE") == 0) {
            if (num_bundles >= MAX_BUNDLES) {
                fprintf(stderr, "vsim: too many bundles\n");
                fclose(f);
                return 1;
            }
            in_bundle = 1;
            for (int i = 0; i < SLOTS_PER_BUNDLE; i++)
                bundles[num_bundles].slots[i].active = 0;
        } else if (strcmp(line, "ENDBUNDLE") == 0) {
            num_bundles++;
            in_bundle = 0;
        } else if (strcmp(line, "END") == 0) {
            break;
        } else if (in_bundle) {
            char slot_name[8], op[16];
            int dst = 0, s0 = 0, s1 = 0, s2 = 0;
            unsigned imm = 0;

            int n = sscanf(line, "%7s %15s %d %d %d %d %u",
                           slot_name, op, &dst, &s0, &s1, &s2, &imm);
            if (n < 2) continue;

            int si = -1;
            if (strcmp(slot_name, "alu0") == 0)      si = 0;
            else if (strcmp(slot_name, "alu1") == 0)  si = 1;
            else if (strcmp(slot_name, "mul") == 0)   si = 2;
            else if (strcmp(slot_name, "mem") == 0)   si = 3;

            if (si >= 0 && strcmp(op, "nop") != 0) {
                Slot *s = &bundles[num_bundles].slots[si];
                strncpy(s->op, op, 15);
                s->op[15] = '\0';
                s->dst = dst;
                s->srcs[0] = s0;
                s->srcs[1] = s1;
                s->srcs[2] = s2;
                s->imm = (uint32_t)imm;
                s->active = 1;
            }
        }
    }

    fclose(f);
    return 0;
}

static int simulate(int trace) {
    memset(regs, 0, sizeof(uint32_t) * (unsigned)num_regs);
    memset(ready_at, 0, sizeof(int) * (unsigned)num_regs);
    int cycle = 0;

    for (int bi = 0; bi < num_bundles; bi++) {
        Bundle *bun = &bundles[bi];

        int has_active = 0;
        for (int i = 0; i < SLOTS_PER_BUNDLE; i++)
            if (bun->slots[i].active) { has_active = 1; break; }
        if (!has_active) { cycle++; continue; }

        /* stall until all source operands are ready */
        int max_rdy = cycle;
        for (int i = 0; i < SLOTS_PER_BUNDLE; i++) {
            Slot *s = &bun->slots[i];
            if (!s->active) continue;
            for (int j = 0; j < 3; j++) {
                int src = s->srcs[j];
                if (src > 0 && src < num_regs && ready_at[src] > max_rdy)
                    max_rdy = ready_at[src];
            }
        }
        cycle = max_rdy;

        /* snapshot regs and mem for read-before-write semantics */
        uint32_t rsnap[MAX_REGS];
        uint32_t msnap[MEM_SIZE];
        memcpy(rsnap, regs, sizeof(uint32_t) * (unsigned)num_regs);
        memcpy(msnap, mem, sizeof(msnap));

        /* execute each active slot */
        for (int i = 0; i < SLOTS_PER_BUNDLE; i++) {
            Slot *s = &bun->slots[i];
            if (!s->active) continue;

            uint32_t a  = (s->srcs[0] > 0 && s->srcs[0] < num_regs)
                          ? rsnap[s->srcs[0]] : 0;
            uint32_t bv = (s->srcs[1] > 0 && s->srcs[1] < num_regs)
                          ? rsnap[s->srcs[1]] : 0;
            uint32_t cv = (s->srcs[2] > 0 && s->srcs[2] < num_regs)
                          ? rsnap[s->srcs[2]] : 0;

            if (strcmp(s->op, "lw") == 0) {
                uint32_t addr = (a + s->imm) % MEM_SIZE;
                uint32_t val = msnap[addr];
                if (s->dst > 0 && s->dst < num_regs) {
                    regs[s->dst] = val;
                    ready_at[s->dst] = cycle + 4;
                }
            } else if (strcmp(s->op, "sw") == 0) {
                uint32_t addr = (a + s->imm) % MEM_SIZE;
                mem[addr] = bv;
            } else {
                uint32_t val = exec_op(s->op, a, bv, cv, s->imm);
                if (s->dst > 0 && s->dst < num_regs) {
                    regs[s->dst] = val;
                    ready_at[s->dst] = cycle + get_latency(s->op);
                }
            }

            if (trace) {
                fprintf(stderr, "  [cycle %3d] bundle %3d slot %d: %-7s",
                        cycle, bi, i, s->op);
                if (s->dst > 0)
                    fprintf(stderr, " r%-3d <-", s->dst);
                if (strcmp(s->op, "lw") == 0 || strcmp(s->op, "sw") == 0)
                    fprintf(stderr, " mem[%u]",
                            (unsigned)((a + s->imm) % MEM_SIZE));
                else
                    fprintf(stderr, " r%d, r%d", s->srcs[0], s->srcs[1]);
                fprintf(stderr, "\n");
            }
        }
        cycle++;
    }
    return cycle;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr,
            "vsim - VLIW Cycle-Accurate Simulator\n"
            "Usage: vsim <input.vbin> [--trace]\n"
            "\n"
            "Reads a .vbin interchange file and simulates the VLIW machine.\n"
            "Output: CYCLES, MEM dump, STATUS on stdout.\n"
            "Pass --trace for per-instruction trace on stderr.\n");
        return 1;
    }

    int trace = 0;
    if (argc > 2 && strcmp(argv[2], "--trace") == 0)
        trace = 1;

    if (parse_vbin(argv[1]) != 0) return 1;

    int cycles = simulate(trace);

    printf("CYCLES %d\n", cycles);
    for (int i = 0; i < data_size; i++)
        printf("MEM %d %u\n", i, (unsigned)mem[i]);
    printf("STATUS OK\n");

    return 0;
}
