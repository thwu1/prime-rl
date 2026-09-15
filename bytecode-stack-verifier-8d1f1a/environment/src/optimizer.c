/*
 * Bytecode Optimizer — Skeleton
 *
 * Reads a BCVF bytecode file, applies optimization passes, and writes
 * the optimized bytecode to a specified output file.
 *
 * Usage: optimizer <input.bc> <output.bc>
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

/* ------------------------------------------------------------------ */
/*  Opcode enumeration                                                */
/* ------------------------------------------------------------------ */
enum {
#define DEF(name, size, n_pop, n_push) OP_##name,
#include "opcode_def.h"
    OP_COUNT
};

typedef struct {
    const char *name;
    uint8_t     size;
    int8_t      n_pop;
    int8_t      n_push;
} OpcodeInfo;

static const OpcodeInfo opcode_info[OP_COUNT] = {
    [OP_invalid]       = { "invalid",       1,  0,  0 },
    [OP_push_i32]      = { "push_i32",      5,  0,  1 },
    [OP_push_const]    = { "push_const",    5,  0,  1 },
    [OP_undefined]     = { "undefined",     1,  0,  1 },
    [OP_null_val]      = { "null_val",      1,  0,  1 },
    [OP_push_false]    = { "push_false",    1,  0,  1 },
    [OP_push_true]     = { "push_true",     1,  0,  1 },
    [OP_object]        = { "object",        1,  0,  1 },
    [OP_drop]          = { "drop",          1,  1,  0 },
    [OP_dup]           = { "dup",           1,  1,  2 },
    [OP_dup2]          = { "dup2",          1,  2,  4 },
    [OP_swap]          = { "swap",          1,  2,  2 },
    [OP_rot3l]         = { "rot3l",         1,  3,  3 },
    [OP_add]           = { "add",           1,  2,  1 },
    [OP_sub]           = { "sub",           1,  2,  1 },
    [OP_mul]           = { "mul",           1,  2,  1 },
    [OP_div_op]        = { "div_op",        1,  2,  1 },
    [OP_mod_op]        = { "mod_op",        1,  2,  1 },
    [OP_neg]           = { "neg",           1,  1,  1 },
    [OP_inc]           = { "inc",           1,  1,  1 },
    [OP_dec]           = { "dec",           1,  1,  1 },
    [OP_shl]           = { "shl",           1,  2,  1 },
    [OP_sar]           = { "sar",           1,  2,  1 },
    [OP_shr]           = { "shr",           1,  2,  1 },
    [OP_bit_and]       = { "bit_and",       1,  2,  1 },
    [OP_bit_or]        = { "bit_or",        1,  2,  1 },
    [OP_bit_xor]       = { "bit_xor",       1,  2,  1 },
    [OP_bit_not]       = { "bit_not",       1,  1,  1 },
    [OP_lnot]          = { "lnot",          1,  1,  1 },
    [OP_eq]            = { "eq",            1,  2,  1 },
    [OP_neq]           = { "neq",           1,  2,  1 },
    [OP_strict_eq]     = { "strict_eq",     1,  2,  1 },
    [OP_strict_neq]    = { "strict_neq",    1,  2,  1 },
    [OP_lt]            = { "lt",            1,  2,  1 },
    [OP_lte]           = { "lte",           1,  2,  1 },
    [OP_gt]            = { "gt",            1,  2,  1 },
    [OP_gte]           = { "gte",           1,  2,  1 },
    [OP_get_loc]       = { "get_loc",       3,  0,  1 },
    [OP_put_loc]       = { "put_loc",       3,  1,  0 },
    [OP_set_loc]       = { "set_loc",       3,  1,  1 },
    [OP_get_arg]       = { "get_arg",       3,  0,  1 },
    [OP_put_arg]       = { "put_arg",       3,  1,  0 },
    [OP_get_field]     = { "get_field",     5,  1,  1 },
    [OP_put_field]     = { "put_field",     5,  2,  0 },
    [OP_get_array_el]  = { "get_array_el",  1,  2,  1 },
    [OP_put_array_el]  = { "put_array_el",  1,  3,  0 },
    [OP_call]          = { "call",          3, -1,  1 },
    [OP_return_val]    = { "return_val",    1,  1,  0 },
    [OP_return_undef]  = { "return_undef",  1,  0,  0 },
    [OP_if_false]      = { "if_false",      5,  1,  0 },
    [OP_if_true]       = { "if_true",       5,  1,  0 },
    [OP_goto_op]       = { "goto_op",       5,  0,  0 },
    [OP_catch]         = { "catch",         5,  0,  0 },
    [OP_end_catch]     = { "end_catch",     1,  0,  0 },
    [OP_throw_op]      = { "throw_op",      1,  1,  0 },
    [OP_typeof_op]     = { "typeof_op",     1,  1,  1 },
    [OP_instanceof_op] = { "instanceof_op", 1,  2,  1 },
    [OP_in_op]         = { "in_op",         1,  2,  1 },
    [OP_nop]           = { "nop",           1,  0,  0 },
};

/* ------------------------------------------------------------------ */
/*  Instruction representation                                        */
/* ------------------------------------------------------------------ */
typedef struct {
    uint8_t  opcode;
    int      orig_offset;   /* byte offset in the original code      */
    int      size;          /* total instruction size in bytes        */
    uint8_t  operand[4];    /* raw operand bytes (size - 1 bytes)    */
    bool     deleted;       /* marked for removal by optimiser       */
} Insn;

typedef struct {
    uint16_t num_locals;
    uint16_t num_args;
    Insn    *insns;
    int      count;
    int      orig_code_len;
} Program;

/* ------------------------------------------------------------------ */
/*  Little-endian helpers                                              */
/* ------------------------------------------------------------------ */
static uint16_t read_u16(const uint8_t *p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}

static int32_t read_i32(const uint8_t *p)
{
    return (int32_t)((uint32_t)p[0]        | ((uint32_t)p[1] << 8) |
                     ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24));
}

static void write_u16(uint8_t *p, uint16_t v)
{
    p[0] = v & 0xFF;
    p[1] = (v >> 8) & 0xFF;
}

static void write_i32(uint8_t *p, int32_t v)
{
    uint32_t u = (uint32_t)v;
    p[0] = u & 0xFF;
    p[1] = (u >> 8) & 0xFF;
    p[2] = (u >> 16) & 0xFF;
    p[3] = (u >> 24) & 0xFF;
}

/* ------------------------------------------------------------------ */
/*  Program I/O                                                       */
/* ------------------------------------------------------------------ */

static bool read_program(const char *path, Program *prog)
{
    FILE *f = fopen(path, "rb");
    if (!f) return false;

    fseek(f, 0, SEEK_END);
    long flen = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (flen < 12) { fclose(f); return false; }

    uint8_t *data = malloc((size_t)flen);
    if (fread(data, 1, (size_t)flen, f) != (size_t)flen) {
        free(data); fclose(f); return false;
    }
    fclose(f);

    if (data[0] != 'B' || data[1] != 'C' || data[2] != 'V' || data[3] != 'F') {
        free(data); return false;
    }

    prog->num_locals = read_u16(data + 4);
    prog->num_args   = read_u16(data + 6);
    uint32_t code_len = (uint32_t)data[8]        | ((uint32_t)data[9] << 8) |
                        ((uint32_t)data[10] << 16) | ((uint32_t)data[11] << 24);

    if (12 + code_len > (uint32_t)flen) { free(data); return false; }

    prog->orig_code_len = (int)code_len;

    /* count instructions */
    const uint8_t *code = data + 12;
    int n = 0;
    size_t pc = 0;
    while (pc < code_len) {
        uint8_t op = code[pc];
        if (op >= OP_COUNT) { free(data); return false; }
        pc += opcode_info[op].size;
        n++;
    }

    prog->insns = calloc((size_t)n, sizeof(Insn));
    prog->count = n;

    /* parse into instruction array */
    pc = 0;
    int idx = 0;
    while (pc < code_len) {
        Insn *insn  = &prog->insns[idx];
        insn->opcode      = code[pc];
        insn->orig_offset = (int)pc;
        insn->size         = opcode_info[insn->opcode].size;
        insn->deleted      = false;
        if (insn->size > 1)
            memcpy(insn->operand, code + pc + 1, (size_t)(insn->size - 1));
        pc += insn->size;
        idx++;
    }

    free(data);
    return true;
}

static bool write_program(const char *path, const Program *prog)
{
    /* compute new code length (skip deleted instructions) */
    int code_len = 0;
    for (int i = 0; i < prog->count; i++) {
        if (!prog->insns[i].deleted)
            code_len += prog->insns[i].size;
    }

    uint8_t header[12];
    header[0] = 'B'; header[1] = 'C'; header[2] = 'V'; header[3] = 'F';
    write_u16(header + 4, prog->num_locals);
    write_u16(header + 6, prog->num_args);
    header[8]  = (uint8_t)(code_len & 0xFF);
    header[9]  = (uint8_t)((code_len >> 8) & 0xFF);
    header[10] = (uint8_t)((code_len >> 16) & 0xFF);
    header[11] = (uint8_t)((code_len >> 24) & 0xFF);

    FILE *f = fopen(path, "wb");
    if (!f) return false;

    fwrite(header, 1, 12, f);

    for (int i = 0; i < prog->count; i++) {
        if (prog->insns[i].deleted) continue;
        const Insn *insn = &prog->insns[i];
        fputc(insn->opcode, f);
        if (insn->size > 1)
            fwrite(insn->operand, 1, (size_t)(insn->size - 1), f);
    }

    fclose(f);
    return true;
}

/* ------------------------------------------------------------------ */
/*  Optimization passes                                               */
/* ------------------------------------------------------------------ */

/* Fold constant integer arithmetic. Return number of changes. */
static int opt_constant_fold(Program *prog)
{
    (void)prog;
    return 0;
}

/* Simplify statically-determined conditional branches. Return number of changes. */
static int opt_dead_branches(Program *prog)
{
    (void)prog;
    return 0;
}

/* Remove instructions unreachable after terminal opcodes. Return number of changes. */
static int opt_dead_code(Program *prog)
{
    (void)prog;
    return 0;
}

/* Shorten branch chains where the target is itself a branch. Return number of changes. */
static int opt_thread_gotos(Program *prog)
{
    (void)prog;
    return 0;
}

/* Remove side-effect-free value push immediately followed by drop. Return number of changes. */
static int opt_push_drop(Program *prog)
{
    (void)prog;
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Compaction and offset rewriting                                   */
/* ------------------------------------------------------------------ */

/* Remove deleted instructions and rewrite all branch offsets for new positions. */
static bool compact_and_rewrite(Program *prog)
{
    (void)prog;
    return true;
}

/* ------------------------------------------------------------------ */
/*  main                                                              */
/* ------------------------------------------------------------------ */
int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <input.bc> <output.bc>\n", argv[0]);
        return 2;
    }

    Program prog;
    memset(&prog, 0, sizeof(prog));

    if (!read_program(argv[1], &prog)) {
        fprintf(stderr, "error: failed to read '%s'\n", argv[1]);
        return 1;
    }

    /* run optimisation passes until fixpoint */
    for (int iter = 0; iter < 20; iter++) {
        int changed = 0;
        changed += opt_constant_fold(&prog);
        changed += opt_dead_branches(&prog);
        changed += opt_push_drop(&prog);
        changed += opt_dead_code(&prog);
        changed += opt_thread_gotos(&prog);
        if (changed == 0)
            break;
    }

    /* compact and rewrite branch offsets */
    if (!compact_and_rewrite(&prog)) {
        fprintf(stderr, "error: compaction failed\n");
        free(prog.insns);
        return 1;
    }

    if (!write_program(argv[2], &prog)) {
        fprintf(stderr, "error: failed to write '%s'\n", argv[2]);
        free(prog.insns);
        return 1;
    }

    free(prog.insns);
    return 0;
}
