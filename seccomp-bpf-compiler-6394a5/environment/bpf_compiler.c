/*
 * bpf_compiler.c - Raw seccomp-BPF filter compiler
 *
 * Reads a policy file and emits a binary cBPF program suitable for
 * seccomp(SECCOMP_SET_MODE_FILTER). The output binary can be loaded
 * directly or inspected with a BPF disassembler/simulator.
 *
 * Policy file format (one rule per line):
 *   default <ACTION>
 *   <syscall_name_or_number> <ACTION> [arg<N> <CMP> <VALUE> [<MASK>]] ...
 *
 * Actions: ALLOW, KILL, KILL_PROCESS, TRAP, LOG, ERRNO(<n>), TRACE(<n>)
 * Comparisons: EQ, NE, GT, GE, LT, LE, MASKED_EQ
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <linux/audit.h>

#define MAX_RULES 64
#define MAX_ARGS_PER_RULE 6
#define MAX_INSNS 4096
#define MAX_LINE 512

/* seccomp_data offsets (for x86_64, little-endian) */
#define SD_OFF_NR        0   /* offsetof(struct seccomp_data, nr) */
#define SD_OFF_ARCH      4   /* offsetof(struct seccomp_data, arch) */
#define SD_OFF_IP        8   /* offsetof(struct seccomp_data, instruction_pointer) */
#define SD_OFF_ARGS     16   /* offsetof(struct seccomp_data, args[0]) */

/* Expected architecture for x86_64 */
#define EXPECTED_ARCH   0x4000003E

/* Argument comparison types */
enum cmp_op {
    CMP_EQ = 0,
    CMP_NE,
    CMP_GT,
    CMP_GE,
    CMP_LT,
    CMP_LE,
    CMP_MASKED_EQ,
};

struct arg_cmp {
    int arg_index;       /* 0-5 */
    enum cmp_op op;
    uint64_t value;
    uint64_t mask;       /* only for MASKED_EQ */
    int active;
};

struct rule {
    int syscall_nr;
    uint32_t action;     /* SECCOMP_RET_xxx | data */
    struct arg_cmp args[MAX_ARGS_PER_RULE];
    int arg_count;
};

struct policy {
    uint32_t default_action;
    struct rule rules[MAX_RULES];
    int rule_count;
};

static struct sock_filter program[MAX_INSNS];
static int insn_count = 0;

/* ------------------------------------------------------------------ */
/* Helpers                                                              */
/* ------------------------------------------------------------------ */

static void emit(uint16_t code, uint8_t jt, uint8_t jf, uint32_t k)
{
    if (insn_count >= MAX_INSNS) {
        fprintf(stderr, "BPF program too large\n");
        exit(1);
    }
    program[insn_count].code = code;
    program[insn_count].jt = jt;
    program[insn_count].jf = jf;
    program[insn_count].k = k;
    insn_count++;
}

/* BPF macros */
#define BPF_LOAD_ABS(off)     emit(BPF_LD | BPF_W | BPF_ABS, 0, 0, (off))
#define BPF_JEQ_K(val, jt, jf) emit(BPF_JMP | BPF_JEQ | BPF_K, (jt), (jf), (val))
#define BPF_JGT_K(val, jt, jf) emit(BPF_JMP | BPF_JGT | BPF_K, (jt), (jf), (val))
#define BPF_JGE_K(val, jt, jf) emit(BPF_JMP | BPF_JGE | BPF_K, (jt), (jf), (val))
#define BPF_JSET_K(val, jt, jf) emit(BPF_JMP | BPF_JSET | BPF_K, (jt), (jf), (val))
#define BPF_AND_K(val)        emit(BPF_ALU | BPF_AND | BPF_K, 0, 0, (val))
#define BPF_RET_K(val)        emit(BPF_RET | BPF_K, 0, 0, (val))
#define BPF_JMP_A(off)        emit(BPF_JMP | BPF_JA, 0, 0, (off))

/* Parse action string to SECCOMP_RET value */
static uint32_t parse_action(const char *s)
{
    if (strcmp(s, "ALLOW") == 0)
        return SECCOMP_RET_ALLOW;
    if (strcmp(s, "KILL") == 0)
        return SECCOMP_RET_KILL_THREAD;
    if (strcmp(s, "KILL_PROCESS") == 0)
        return SECCOMP_RET_KILL_PROCESS;
    if (strcmp(s, "TRAP") == 0)
        return SECCOMP_RET_TRAP;
    if (strcmp(s, "LOG") == 0)
        return SECCOMP_RET_LOG;
    if (strncmp(s, "ERRNO(", 6) == 0) {
        unsigned val = 0;
        sscanf(s + 6, "%u", &val);
        return SECCOMP_RET_ERRNO | (val & SECCOMP_RET_DATA);
    }
    if (strncmp(s, "TRACE(", 6) == 0) {
        unsigned val = 0;
        sscanf(s + 6, "%u", &val);
        return SECCOMP_RET_TRACE | (val & SECCOMP_RET_DATA);
    }
    fprintf(stderr, "Unknown action: %s\n", s);
    exit(1);
}

/* Resolve syscall name to number on x86_64 (common subset) */
static int resolve_syscall(const char *name)
{
    struct { const char *name; int nr; } table[] = {
        {"read",            0},
        {"write",           1},
        {"open",            2},
        {"close",           3},
        {"stat",            4},
        {"fstat",           5},
        {"lstat",           6},
        {"poll",            7},
        {"lseek",           8},
        {"mmap",            9},
        {"mprotect",       10},
        {"munmap",         11},
        {"brk",            12},
        {"rt_sigaction",   13},
        {"rt_sigprocmask", 14},
        {"rt_sigreturn",   15},
        {"ioctl",          16},
        {"access",         21},
        {"pipe",           22},
        {"select",         23},
        {"mremap",         25},
        {"dup",            32},
        {"dup2",           33},
        {"pause",          34},
        {"nanosleep",      35},
        {"getpid",         39},
        {"socket",         41},
        {"connect",        42},
        {"accept",         43},
        {"sendto",         44},
        {"recvfrom",       45},
        {"bind",           49},
        {"listen",         50},
        {"clone",          56},
        {"fork",           57},
        {"execve",         59},
        {"exit",           60},
        {"wait4",          61},
        {"kill",           62},
        {"fcntl",          72},
        {"flock",          73},
        {"fsync",          74},
        {"getcwd",         79},
        {"chdir",          80},
        {"rename",         82},
        {"mkdir",          83},
        {"rmdir",          84},
        {"creat",          85},
        {"unlink",         87},
        {"chmod",          90},
        {"chown",          92},
        {"getuid",         102},
        {"getgid",         104},
        {"geteuid",        107},
        {"getegid",        108},
        {"setuid",         105},
        {"setgid",         106},
        {"getppid",        110},
        {"getpgrp",        111},
        {"setsid",         112},
        {"sigaltstack",    131},
        {"fstatfs",        138},
        {"prctl",          157},
        {"arch_prctl",     158},
        {"gettid",         186},
        {"futex",          202},
        {"set_tid_address", 218},
        {"clock_gettime",  228},
        {"exit_group",     231},
        {"openat",         257},
        {"newfstatat",     262},
        {"set_robust_list", 273},
        {"prlimit64",      302},
        {"getrandom",      318},
        {"memfd_create",   319},
        {"statx",          332},
        {"rseq",           334},
        {"clone3",         435},
        {NULL, -1}
    };

    /* Try numeric */
    char *end;
    long nr = strtol(name, &end, 10);
    if (*end == '\0')
        return (int)nr;

    for (int i = 0; table[i].name; i++) {
        if (strcmp(name, table[i].name) == 0)
            return table[i].nr;
    }

    fprintf(stderr, "Unknown syscall: %s\n", name);
    exit(1);
}

static enum cmp_op parse_cmp(const char *s)
{
    if (strcmp(s, "EQ") == 0) return CMP_EQ;
    if (strcmp(s, "NE") == 0) return CMP_NE;
    if (strcmp(s, "GT") == 0) return CMP_GT;
    if (strcmp(s, "GE") == 0) return CMP_GE;
    if (strcmp(s, "LT") == 0) return CMP_LT;
    if (strcmp(s, "LE") == 0) return CMP_LE;
    if (strcmp(s, "MASKED_EQ") == 0) return CMP_MASKED_EQ;
    fprintf(stderr, "Unknown comparison: %s\n", s);
    exit(1);
}

/* ------------------------------------------------------------------ */
/* Policy parser                                                        */
/* ------------------------------------------------------------------ */

static void parse_policy(const char *filename, struct policy *pol)
{
    FILE *f = fopen(filename, "r");
    if (!f) {
        perror(filename);
        exit(1);
    }

    memset(pol, 0, sizeof(*pol));
    pol->default_action = SECCOMP_RET_KILL_THREAD;

    char line[MAX_LINE];
    while (fgets(line, sizeof(line), f)) {
        /* Strip comment and newline */
        char *hash = strchr(line, '#');
        if (hash) *hash = '\0';
        char *nl = strchr(line, '\n');
        if (nl) *nl = '\0';

        /* Skip blank lines */
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '\0') continue;

        char tokens[16][128];
        int ntok = 0;
        char *tok = strtok(p, " \t");
        while (tok && ntok < 16) {
            strncpy(tokens[ntok], tok, 127);
            tokens[ntok][127] = '\0';
            ntok++;
            tok = strtok(NULL, " \t");
        }
        if (ntok < 2) continue;

        if (strcmp(tokens[0], "default") == 0) {
            pol->default_action = parse_action(tokens[1]);
            continue;
        }

        /* Syscall rule */
        struct rule *r = &pol->rules[pol->rule_count];
        r->syscall_nr = resolve_syscall(tokens[0]);
        r->action = parse_action(tokens[1]);
        r->arg_count = 0;

        int i = 2;
        while (i + 2 < ntok) {
            /* argN CMP VALUE [MASK] */
            if (strncmp(tokens[i], "arg", 3) != 0) break;
            int ai = tokens[i][3] - '0';
            if (ai < 0 || ai > 5) break;

            struct arg_cmp *ac = &r->args[r->arg_count];
            ac->arg_index = ai;
            ac->op = parse_cmp(tokens[i+1]);
            ac->value = strtoull(tokens[i+2], NULL, 0);
            ac->mask = 0xFFFFFFFFFFFFFFFFULL;
            ac->active = 1;

            if (ac->op == CMP_MASKED_EQ && i + 3 < ntok) {
                ac->mask = strtoull(tokens[i+3], NULL, 0);
                i += 4;
            } else {
                i += 3;
            }
            r->arg_count++;
        }

        pol->rule_count++;
    }

    fclose(f);
}

/* ------------------------------------------------------------------ */
/* BPF code generation                                                  */
/* ------------------------------------------------------------------ */

/*
 * Compute the offset into seccomp_data for an argument's low or high
 * 32-bit word.  seccomp_data.args[] are uint64_t starting at byte 16.
 * Each argument occupies 8 bytes.
 */
static uint32_t arg_offset_lo(int arg_index)
{
    return SD_OFF_ARGS + arg_index * 8 + 4;
}

static uint32_t arg_offset_hi(int arg_index)
{
    return SD_OFF_ARGS + arg_index * 8;
}

/*
 * Count the number of BPF instructions needed for a single argument
 * comparison.  Used to calculate forward jump offsets.
 */
static int arg_cmp_insn_count(const struct arg_cmp *ac)
{
    switch (ac->op) {
    case CMP_EQ:
        if (ac->value <= 0xFFFFFFFF)
            return 2;  /* load + jeq */
        return 5;      /* full 64-bit check */
    case CMP_NE:
        if (ac->value <= 0xFFFFFFFF)
            return 2;
        return 5;
    case CMP_GT:
    case CMP_GE:
    case CMP_LT:
    case CMP_LE:
        return 2;      /* load + compare */
    case CMP_MASKED_EQ:
        return 3;      /* load + and + jeq */
    default:
        return 2;
    }
}

/*
 * Emit BPF instructions for a single argument comparison.
 * On match, falls through past the block.
 * On no-match, jumps fail_offset instructions past the end of this block.
 */
static void emit_arg_cmp(const struct arg_cmp *ac, int fail_offset)
{
    uint32_t lo = (uint32_t)(ac->value & 0xFFFFFFFF);
    uint32_t hi = (uint32_t)(ac->value >> 32);

    switch (ac->op) {
    case CMP_EQ:
        if (hi == 0) {
            BPF_LOAD_ABS(arg_offset_lo(ac->arg_index));
            BPF_JEQ_K(lo, 0, fail_offset);
        } else {
            /* Check high word first, then low word */
            BPF_LOAD_ABS(arg_offset_hi(ac->arg_index));
            BPF_JEQ_K(hi, 0, fail_offset + 2);
            BPF_LOAD_ABS(arg_offset_lo(ac->arg_index));
            BPF_JEQ_K(lo, 0, fail_offset);
        }
        break;

    case CMP_NE:
        if (hi == 0) {
            BPF_LOAD_ABS(arg_offset_lo(ac->arg_index));
            /* NE: if equal, that's a failure */
            BPF_JEQ_K(lo, fail_offset, 0);
        } else {
            /* 64-bit NE: not-equal if either word differs */
            BPF_LOAD_ABS(arg_offset_hi(ac->arg_index));
            BPF_JEQ_K(hi, 0, 2);
            BPF_JMP_A(fail_offset + 1);
            BPF_LOAD_ABS(arg_offset_lo(ac->arg_index));
            BPF_JEQ_K(lo, fail_offset, 0);
        }
        break;

    case CMP_GT:
        BPF_LOAD_ABS(arg_offset_lo(ac->arg_index));
        BPF_JGT_K(lo, 0, fail_offset);
        break;

    case CMP_GE:
        BPF_LOAD_ABS(arg_offset_lo(ac->arg_index));
        BPF_JGE_K(lo, 0, fail_offset);
        break;

    case CMP_LT:
        /* LT is !(GE) */
        BPF_LOAD_ABS(arg_offset_lo(ac->arg_index));
        BPF_JGE_K(lo, fail_offset, 0);
        break;

    case CMP_LE:
        /* LE is !(GT) */
        BPF_LOAD_ABS(arg_offset_lo(ac->arg_index));
        BPF_JGT_K(lo, fail_offset, 0);
        break;

    case CMP_MASKED_EQ:
        /* Apply mask and check equality */
        BPF_LOAD_ABS(arg_offset_lo(ac->arg_index));
        BPF_AND_K((uint32_t)(ac->mask & 0xFFFFFFFF));
        BPF_JEQ_K(lo, 0, fail_offset);
        break;
    }
}

/*
 * Emit the complete BPF program for the given policy.
 *
 * Structure:
 *   1. Validate architecture (must be x86_64)
 *   2. Load syscall number
 *   3. For each rule: compare syscall, compare args, emit action
 *   4. Default action
 */
static void emit_program(const struct policy *pol)
{
    insn_count = 0;

    /* ---- Architecture check ---- */
    BPF_LOAD_ABS(SD_OFF_ARCH);
    /* If arch matches expected, skip over the kill instruction */
    BPF_JEQ_K(EXPECTED_ARCH, 1, 0);
    BPF_RET_K(SECCOMP_RET_KILL_THREAD);

    /* ---- Syscall number dispatch ---- */
    BPF_LOAD_ABS(SD_OFF_NR);

    for (int r = 0; r < pol->rule_count; r++) {
        const struct rule *rule = &pol->rules[r];

        /* Calculate total instructions for this rule's arg checks + action */
        int arg_insns = 0;
        for (int a = 0; a < rule->arg_count; a++) {
            arg_insns += arg_cmp_insn_count(&rule->args[a]);
        }
        int rule_body_size = arg_insns + 1; /* +1 for the RET */

        /* If syscall doesn't match, skip past this rule's body */
        BPF_JEQ_K(rule->syscall_nr, 0, rule_body_size);

        /* Emit argument comparisons */
        int remaining_insns = arg_insns + 1;
        for (int a = 0; a < rule->arg_count; a++) {
            remaining_insns -= arg_cmp_insn_count(&rule->args[a]);
            emit_arg_cmp(&rule->args[a], remaining_insns);
        }

        /* Emit action for this rule */
        BPF_RET_K(rule->action);

        /* Reload syscall number for next rule comparison */
        if (r + 1 < pol->rule_count) {
            BPF_LOAD_ABS(SD_OFF_NR);
        }
    }

    /* Default action */
    BPF_RET_K(pol->default_action);
}

/* ------------------------------------------------------------------ */
/* Main                                                                 */
/* ------------------------------------------------------------------ */

int main(int argc, char *argv[])
{
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <policy_file> <output_bpf>\n", argv[0]);
        return 1;
    }

    struct policy pol;
    parse_policy(argv[1], &pol);

    emit_program(&pol);

    /* Write binary BPF program */
    FILE *out = fopen(argv[2], "wb");
    if (!out) {
        perror(argv[2]);
        return 1;
    }

    size_t written = fwrite(program, sizeof(struct sock_filter), insn_count, out);
    if (written != (size_t)insn_count) {
        fprintf(stderr, "Short write: %zu of %d\n", written, insn_count);
        fclose(out);
        return 1;
    }

    fclose(out);
    fprintf(stderr, "Wrote %d BPF instructions to %s\n", insn_count, argv[2]);
    return 0;
}
