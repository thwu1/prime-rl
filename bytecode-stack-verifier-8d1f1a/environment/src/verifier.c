/*
 * Bytecode Stack Verifier
 *
 * Validates bytecode programs for a stack-based virtual machine by
 * performing abstract interpretation over the instruction stream.
 *
 * Reads a bytecode binary file whose format is:
 *   Bytes  0-3:  magic "BCVF"
 *   Bytes  4-5:  num_locals  (u16 LE)
 *   Bytes  6-7:  num_args    (u16 LE)
 *   Bytes  8-11: code_len    (u32 LE)
 *   Bytes 12+:   bytecode instructions
 *
 * Output (stdout):
 *   On success: RESULT: VALID / MAX_STACK: N / DEPTH[offset]: N ...
 *   On failure: RESULT: INVALID / ERROR: description ...
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdarg.h>

/* ------------------------------------------------------------------ */
/*  Opcode enumeration (generated from the specification header)      */
/* ------------------------------------------------------------------ */
enum {
#define DEF(name, size, n_pop, n_push) OP_##name,
#include "opcode_def.h"
    OP_COUNT
};

/* ------------------------------------------------------------------ */
/*  Opcode metadata                                                   */
/* ------------------------------------------------------------------ */
typedef struct {
    const char *name;
    uint8_t     size;
    int8_t      n_pop;   /* -1 = variable, resolved at verification   */
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
    [OP_set_loc]       = { "set_loc",       3,  1,  0 },
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
/*  File-format magic                                                 */
/* ------------------------------------------------------------------ */
#define MAGIC_0 0x42  /* 'B' */
#define MAGIC_1 0x43  /* 'C' */
#define MAGIC_2 0x56  /* 'V' */
#define MAGIC_3 0x46  /* 'F' */

#define MAX_ERRORS 32

/* ------------------------------------------------------------------ */
/*  Little-endian readers                                             */
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

/* ------------------------------------------------------------------ */
/*  Verification state                                                */
/* ------------------------------------------------------------------ */
typedef struct {
    const uint8_t *code;
    size_t         code_len;
    int            num_locals;
    int            num_args;

    bool          *insn_start;     /* bitmap: true at each insn head  */
    int           *stack_depth;    /* per-offset depth, -1 = unvisited*/

    int           *worklist;
    int            wl_head;
    int            wl_tail;
    int            wl_cap;

    char           errors[MAX_ERRORS][256];
    int            error_count;
    int            max_stack;
} VerifyState;

static void add_error(VerifyState *vs, const char *fmt, ...)
{
    if (vs->error_count >= MAX_ERRORS)
        return;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(vs->errors[vs->error_count], 256, fmt, ap);
    va_end(ap);
    vs->error_count++;
}

/* ---- worklist (FIFO) ---- */

static void wl_push(VerifyState *vs, int offset)
{
    for (int i = vs->wl_head; i < vs->wl_tail; i++) {
        if (vs->worklist[i] == offset)
            return;   /* already queued */
    }
    if (vs->wl_tail >= vs->wl_cap) {
        vs->wl_cap = vs->wl_cap ? vs->wl_cap * 2 : 64;
        vs->worklist = realloc(vs->worklist, (size_t)vs->wl_cap * sizeof(int));
    }
    vs->worklist[vs->wl_tail++] = offset;
}

static int wl_pop(VerifyState *vs)
{
    return vs->worklist[vs->wl_head++];
}

static bool wl_empty(const VerifyState *vs)
{
    return vs->wl_head >= vs->wl_tail;
}

/* ------------------------------------------------------------------ */
/*  Propagate stack depth to a successor instruction                  */
/* ------------------------------------------------------------------ */
static void propagate(VerifyState *vs, int target, int depth)
{
    if (target < 0 || target >= (int)vs->code_len) {
        add_error(vs, "branch target %d out of bounds [0, %zu)",
                  target, vs->code_len);
        return;
    }
    if (!vs->insn_start[target]) {
        add_error(vs, "branch target %d is not an instruction boundary",
                  target);
        return;
    }
    if (vs->stack_depth[target] == -1) {
        /* first visit */
        vs->stack_depth[target] = depth;
        if (depth > vs->max_stack)
            vs->max_stack = depth;
        wl_push(vs, target);
    } else if (vs->stack_depth[target] != depth) {
        add_error(vs,
                  "inconsistent stack depth at offset %d: "
                  "expected %d, got %d",
                  target, vs->stack_depth[target], depth);
    }
}

/* ------------------------------------------------------------------ */
/*  Resolve variable-pop count                                        */
/* ------------------------------------------------------------------ */
static int get_dynamic_pop(const VerifyState *vs, int pc)
{
    uint8_t op = vs->code[pc];
    switch (op) {
    case OP_call: {
        uint16_t arg_count = read_u16(vs->code + pc + 1);
        return arg_count;
    }
    default:
        return 0;
    }
}

/* ------------------------------------------------------------------ */
/*  Phase 1 -- scan bytecode, mark instruction boundaries             */
/* ------------------------------------------------------------------ */
static bool scan_instructions(VerifyState *vs)
{
    size_t pc = 0;
    while (pc < vs->code_len) {
        uint8_t op = vs->code[pc];
        if (op >= OP_COUNT || op == OP_invalid) {
            add_error(vs, "invalid opcode 0x%02x at offset %zu", op, pc);
            return false;
        }
        vs->insn_start[pc] = true;
        int sz = opcode_info[op].size;
        if (pc + sz > vs->code_len) {
            add_error(vs,
                      "instruction at offset %zu truncated "
                      "(need %d bytes, have %zu)",
                      pc, sz, vs->code_len - pc);
            return false;
        }
        pc += sz;
    }
    return true;
}

/* ------------------------------------------------------------------ */
/*  Phase 2 -- abstract interpretation (worklist algorithm)           */
/* ------------------------------------------------------------------ */
static void verify_flow(VerifyState *vs)
{
    /* initialise every offset as unvisited */
    for (size_t i = 0; i < vs->code_len; i++)
        vs->stack_depth[i] = -1;

    /* seed: first instruction starts with an empty stack */
    vs->stack_depth[0] = 0;
    wl_push(vs, 0);

    while (!wl_empty(vs)) {
        int pc       = wl_pop(vs);
        int depth    = vs->stack_depth[pc];
        uint8_t op   = vs->code[pc];

        int n_pop    = opcode_info[op].n_pop;
        int n_push   = opcode_info[op].n_push;

        /* resolve variable-pop instructions */
        if (n_pop < 0)
            n_pop = get_dynamic_pop(vs, pc);

        /* stack underflow? */
        if (depth < n_pop) {
            add_error(vs,
                      "stack underflow at offset %d: depth=%d, need=%d",
                      pc, depth, n_pop);
            continue;
        }

        int new_depth = depth - n_pop + n_push;
        if (new_depth > vs->max_stack)
            vs->max_stack = new_depth;

        int sz = opcode_info[op].size;

        switch (op) {

        /* ---- terminals ---- */
        case OP_return_val:
        case OP_return_undef:
        case OP_throw_op:
            /* no successor */
            break;

        /* ---- conditional branches ---- */
        case OP_if_false:
        case OP_if_true: {
            int32_t rel = read_i32(vs->code + pc + 1);
            int target  = pc + rel;
            propagate(vs, target, new_depth);
            break;
        }

        /* ---- unconditional jump ---- */
        case OP_goto_op: {
            int32_t rel = read_i32(vs->code + pc + 1);
            int target  = pc + rel;
            if (target < 0 || target >= (int)vs->code_len) {
                add_error(vs, "goto target %d out of bounds", target);
            }
            break;
        }

        /* ---- exception handler registration ---- */
        case OP_catch: {
            int32_t rel  = read_i32(vs->code + pc + 1);
            int handler  = pc + rel;
            propagate(vs, handler, new_depth);
            /* normal flow continues to next instruction */
            if (pc + sz < (int)vs->code_len)
                propagate(vs, pc + sz, new_depth);
            break;
        }

        /* ---- all other instructions: fall through ---- */
        default:
            if (pc + sz < (int)vs->code_len) {
                propagate(vs, pc + sz, new_depth);
            } else if (pc + sz == (int)vs->code_len) {
                add_error(vs, "execution falls off end at offset %d", pc);
            }
            break;
        }
    }
}

/* ------------------------------------------------------------------ */
/*  main                                                              */
/* ------------------------------------------------------------------ */
int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <bytecode_file>\n", argv[0]);
        return 2;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "error: cannot open '%s'\n", argv[1]);
        return 2;
    }

    fseek(f, 0, SEEK_END);
    long file_len = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (file_len < 12) {
        fprintf(stderr, "error: file too small for header\n");
        fclose(f);
        return 2;
    }

    uint8_t *data = malloc((size_t)file_len);
    if (fread(data, 1, (size_t)file_len, f) != (size_t)file_len) {
        fprintf(stderr, "error: short read\n");
        free(data);
        fclose(f);
        return 2;
    }
    fclose(f);

    /* validate magic */
    if (data[0] != MAGIC_0 || data[1] != MAGIC_1 ||
        data[2] != MAGIC_2 || data[3] != MAGIC_3) {
        fprintf(stderr, "error: bad magic number\n");
        free(data);
        return 2;
    }

    uint16_t num_locals = read_u16(data + 4);
    uint16_t num_args   = read_u16(data + 6);
    uint32_t code_len   = (uint32_t)data[8]        | ((uint32_t)data[9]  << 8) |
                          ((uint32_t)data[10] << 16) | ((uint32_t)data[11] << 24);

    if (12 + code_len > (uint32_t)file_len) {
        fprintf(stderr, "error: code_len %u exceeds file size\n", code_len);
        free(data);
        return 2;
    }

    /* set up verification state */
    VerifyState vs;
    memset(&vs, 0, sizeof(vs));
    vs.code       = data + 12;
    vs.code_len   = code_len;
    vs.num_locals = num_locals;
    vs.num_args   = num_args;
    vs.insn_start   = calloc(code_len, sizeof(bool));
    vs.stack_depth  = calloc(code_len, sizeof(int));
    vs.wl_cap       = 64;
    vs.worklist     = malloc((size_t)vs.wl_cap * sizeof(int));

    /* phase 1: scan */
    bool ok = scan_instructions(&vs);

    /* phase 2: abstract interpretation */
    if (ok && code_len > 0)
        verify_flow(&vs);

    /* output */
    if (vs.error_count == 0) {
        printf("RESULT: VALID\n");
        printf("MAX_STACK: %d\n", vs.max_stack);
        for (size_t i = 0; i < code_len; i++) {
            if (vs.insn_start[i])
                printf("DEPTH[%zu]: %d\n", i, vs.stack_depth[i]);
        }
    } else {
        printf("RESULT: INVALID\n");
        for (int i = 0; i < vs.error_count; i++)
            printf("ERROR: %s\n", vs.errors[i]);
    }

    free(vs.insn_start);
    free(vs.stack_depth);
    free(vs.worklist);
    free(data);

    return (vs.error_count > 0) ? 1 : 0;
}
