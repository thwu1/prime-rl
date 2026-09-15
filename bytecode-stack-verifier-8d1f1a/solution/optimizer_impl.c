/*
 * Bytecode Optimizer — Complete Implementation
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
    int      orig_offset;
    int      size;
    uint8_t  operand[4];
    bool     deleted;
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

static int opt_constant_fold(Program *prog)
{
    int changed = 0;
    for (int i = 0; i < prog->count; i++) {
        if (prog->insns[i].deleted || prog->insns[i].opcode != OP_push_i32)
            continue;
        /* find next non-deleted instruction */
        int j = i + 1;
        while (j < prog->count && prog->insns[j].deleted) j++;
        if (j >= prog->count || prog->insns[j].opcode != OP_push_i32)
            continue;
        /* find the one after that */
        int k = j + 1;
        while (k < prog->count && prog->insns[k].deleted) k++;
        if (k >= prog->count)
            continue;
        uint8_t aop = prog->insns[k].opcode;
        if (aop != OP_add && aop != OP_sub && aop != OP_mul)
            continue;

        int32_t x = read_i32(prog->insns[i].operand);
        int32_t y = read_i32(prog->insns[j].operand);
        int32_t r;
        if (aop == OP_add)      r = x + y;
        else if (aop == OP_sub) r = x - y;
        else                    r = x * y;

        write_i32(prog->insns[i].operand, r);
        prog->insns[j].deleted = true;
        prog->insns[k].deleted = true;
        changed++;
    }
    return changed;
}

static int opt_dead_branches(Program *prog)
{
    int changed = 0;
    for (int i = 0; i < prog->count; i++) {
        if (prog->insns[i].deleted) continue;
        uint8_t op1 = prog->insns[i].opcode;
        if (op1 != OP_push_true && op1 != OP_push_false) continue;

        int j = i + 1;
        while (j < prog->count && prog->insns[j].deleted) j++;
        if (j >= prog->count) continue;
        uint8_t op2 = prog->insns[j].opcode;
        if (op2 != OP_if_false && op2 != OP_if_true) continue;

        bool val = (op1 == OP_push_true);
        bool takes_branch = (val && op2 == OP_if_true) ||
                            (!val && op2 == OP_if_false);

        prog->insns[i].deleted = true;
        if (takes_branch) {
            /* convert conditional to unconditional goto */
            prog->insns[j].opcode = OP_goto_op;
        } else {
            /* branch never taken — delete it entirely */
            prog->insns[j].deleted = true;
        }
        changed++;
    }
    return changed;
}

static int opt_dead_code(Program *prog)
{
    /* build set of live branch targets */
    bool *is_target = calloc((size_t)(prog->orig_code_len + 1), sizeof(bool));
    if (!is_target) return 0;
    for (int i = 0; i < prog->count; i++) {
        Insn *insn = &prog->insns[i];
        if (insn->deleted) continue;
        if (insn->opcode == OP_if_false || insn->opcode == OP_if_true ||
            insn->opcode == OP_goto_op  || insn->opcode == OP_catch) {
            int32_t rel = read_i32(insn->operand);
            int target = insn->orig_offset + rel;
            if (target >= 0 && target <= prog->orig_code_len)
                is_target[target] = true;
        }
    }

    int changed = 0;
    bool dead = false;
    for (int i = 0; i < prog->count; i++) {
        Insn *insn = &prog->insns[i];
        if (insn->deleted) continue;

        if (dead) {
            if (is_target[insn->orig_offset]) {
                dead = false;
            } else {
                insn->deleted = true;
                changed++;
                continue;
            }
        }

        if (insn->opcode == OP_return_val  || insn->opcode == OP_return_undef ||
            insn->opcode == OP_throw_op    || insn->opcode == OP_goto_op) {
            dead = true;
        }
    }

    free(is_target);
    return changed;
}

static int opt_thread_gotos(Program *prog)
{
    /* build offset -> instruction index map */
    int map_sz = prog->orig_code_len;
    if (map_sz <= 0) return 0;
    int *off2idx = malloc((size_t)map_sz * sizeof(int));
    if (!off2idx) return 0;
    memset(off2idx, 0xFF, (size_t)map_sz * sizeof(int));
    for (int i = 0; i < prog->count; i++) {
        if (!prog->insns[i].deleted && prog->insns[i].orig_offset < map_sz)
            off2idx[prog->insns[i].orig_offset] = i;
    }

    int changed = 0;
    for (int i = 0; i < prog->count; i++) {
        Insn *insn = &prog->insns[i];
        if (insn->deleted) continue;
        if (insn->opcode != OP_goto_op  && insn->opcode != OP_if_false &&
            insn->opcode != OP_if_true  && insn->opcode != OP_catch)
            continue;

        int32_t rel = read_i32(insn->operand);
        int target_off = insn->orig_offset + rel;

        int depth = 0;
        while (depth < 100) {
            if (target_off < 0 || target_off >= map_sz) break;
            int tidx = off2idx[target_off];
            if (tidx < 0) break;
            if (prog->insns[tidx].deleted) break;
            if (prog->insns[tidx].opcode != OP_goto_op) break;

            int32_t next_rel = read_i32(prog->insns[tidx].operand);
            target_off = prog->insns[tidx].orig_offset + next_rel;
            depth++;
        }

        int32_t new_rel = target_off - insn->orig_offset;
        if (new_rel != rel) {
            write_i32(insn->operand, new_rel);
            changed++;
        }
    }

    free(off2idx);
    return changed;
}

static int opt_push_drop(Program *prog)
{
    int changed = 0;
    for (int i = 0; i < prog->count; i++) {
        Insn *insn = &prog->insns[i];
        if (insn->deleted) continue;

        uint8_t op = insn->opcode;
        if (op != OP_push_i32   && op != OP_push_const &&
            op != OP_push_true  && op != OP_push_false &&
            op != OP_undefined  && op != OP_null_val   && op != OP_object)
            continue;

        int j = i + 1;
        while (j < prog->count && prog->insns[j].deleted) j++;
        if (j >= prog->count) break;

        if (prog->insns[j].opcode == OP_drop) {
            insn->deleted = true;
            prog->insns[j].deleted = true;
            changed++;
        }
    }
    return changed;
}

/* ------------------------------------------------------------------ */
/*  Compaction and offset rewriting                                   */
/* ------------------------------------------------------------------ */

static bool compact_and_rewrite(Program *prog)
{
    /* 1. Build offset map: orig_offset -> new byte offset */
    int *offset_map = calloc((size_t)(prog->orig_code_len + 1), sizeof(int));
    if (!offset_map) return false;

    int new_off = 0;
    for (int i = 0; i < prog->count; i++) {
        offset_map[prog->insns[i].orig_offset] = new_off;
        if (!prog->insns[i].deleted)
            new_off += prog->insns[i].size;
    }
    offset_map[prog->orig_code_len] = new_off;

    /* 2. Rewrite branch operands */
    for (int i = 0; i < prog->count; i++) {
        Insn *insn = &prog->insns[i];
        if (insn->deleted) continue;

        if (insn->opcode == OP_if_false || insn->opcode == OP_if_true ||
            insn->opcode == OP_goto_op  || insn->opcode == OP_catch) {
            int32_t old_rel = read_i32(insn->operand);
            int old_target = insn->orig_offset + old_rel;
            if (old_target < 0 || old_target > prog->orig_code_len) {
                free(offset_map);
                return false;
            }
            int32_t new_rel = offset_map[old_target] -
                              offset_map[insn->orig_offset];
            write_i32(insn->operand, new_rel);
        }
    }

    /* 3. Remove deleted instructions from array */
    int j = 0;
    for (int i = 0; i < prog->count; i++) {
        if (!prog->insns[i].deleted) {
            prog->insns[j] = prog->insns[i];
            j++;
        }
    }
    prog->count = j;

    free(offset_map);
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
