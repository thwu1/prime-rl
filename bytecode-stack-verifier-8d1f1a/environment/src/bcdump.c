/*
 * Bytecode Disassembler
 *
 * Reads a BCVF bytecode file and prints human-readable disassembly.
 *
 * Usage: bcdump <file.bc>
 *
 * Output format:
 *   ; BCVF num_locals=N num_args=N code_len=N
 *   OFFSET: OPNAME
 *   OFFSET: OPNAME OPERAND
 *   OFFSET: OPNAME OPERAND -> TARGET
 *   ; SUMMARY instructions=N code_bytes=N
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* ------------------------------------------------------------------ */
/*  Opcode enumeration (generated from the specification header)      */
/* ------------------------------------------------------------------ */
enum {
#define DEF(name, size, n_pop, n_push) OP_##name,
#include "opcode_def.h"
    OP_COUNT
};

/* ------------------------------------------------------------------ */
/*  Opcode metadata (name and size only — sufficient for disassembly) */
/* ------------------------------------------------------------------ */
typedef struct {
    const char *name;
    uint8_t     size;
} OpcodeEntry;

static const OpcodeEntry opcode_table[OP_COUNT] = {
    [OP_invalid]       = { "invalid",       1 },
    [OP_push_i32]      = { "push_i32",      5 },
    [OP_push_const]    = { "push_const",    5 },
    [OP_undefined]     = { "undefined",     1 },
    [OP_null_val]      = { "null_val",      1 },
    [OP_push_false]    = { "push_false",    1 },
    [OP_push_true]     = { "push_true",     1 },
    [OP_object]        = { "object",        1 },
    [OP_drop]          = { "drop",          1 },
    [OP_dup]           = { "dup",           1 },
    [OP_dup2]          = { "dup2",          1 },
    [OP_swap]          = { "swap",          1 },
    [OP_rot3l]         = { "rot3l",         1 },
    [OP_add]           = { "add",           1 },
    [OP_sub]           = { "sub",           1 },
    [OP_mul]           = { "mul",           1 },
    [OP_div_op]        = { "div_op",        1 },
    [OP_mod_op]        = { "mod_op",        1 },
    [OP_neg]           = { "neg",           1 },
    [OP_inc]           = { "inc",           1 },
    [OP_dec]           = { "dec",           1 },
    [OP_shl]           = { "shl",           1 },
    [OP_sar]           = { "sar",           1 },
    [OP_shr]           = { "shr",           1 },
    [OP_bit_and]       = { "bit_and",       1 },
    [OP_bit_or]        = { "bit_or",        1 },
    [OP_bit_xor]       = { "bit_xor",       1 },
    [OP_bit_not]       = { "bit_not",       1 },
    [OP_lnot]          = { "lnot",          1 },
    [OP_eq]            = { "eq",            1 },
    [OP_neq]           = { "neq",           1 },
    [OP_strict_eq]     = { "strict_eq",     1 },
    [OP_strict_neq]    = { "strict_neq",    1 },
    [OP_lt]            = { "lt",            1 },
    [OP_lte]           = { "lte",           1 },
    [OP_gt]            = { "gt",            1 },
    [OP_gte]           = { "gte",           1 },
    [OP_get_loc]       = { "get_loc",       3 },
    [OP_put_loc]       = { "put_loc",       3 },
    [OP_set_loc]       = { "set_loc",       3 },
    [OP_get_arg]       = { "get_arg",       3 },
    [OP_put_arg]       = { "put_arg",       3 },
    [OP_get_field]     = { "get_field",     5 },
    [OP_put_field]     = { "put_field",     5 },
    [OP_get_array_el]  = { "get_array_el",  1 },
    [OP_put_array_el]  = { "put_array_el",  1 },
    [OP_call]          = { "call",          3 },
    [OP_return_val]    = { "return_val",    1 },
    [OP_return_undef]  = { "return_undef",  1 },
    [OP_if_false]      = { "if_false",      5 },
    [OP_if_true]       = { "if_true",       5 },
    [OP_goto_op]       = { "goto_op",       5 },
    [OP_catch]         = { "catch",         5 },
    [OP_end_catch]     = { "end_catch",     1 },
    [OP_throw_op]      = { "throw_op",      1 },
    [OP_typeof_op]     = { "typeof_op",     1 },
    [OP_instanceof_op] = { "instanceof_op", 1 },
    [OP_in_op]         = { "in_op",         1 },
    [OP_nop]           = { "nop",           1 },
};

/* ------------------------------------------------------------------ */
/*  Little-endian readers                                             */
/* ------------------------------------------------------------------ */
static int32_t read_i32(const uint8_t *p)
{
    return (int32_t)((uint32_t)p[0]        | ((uint32_t)p[1] << 8) |
                     ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24));
}

/* ------------------------------------------------------------------ */
/*  Branch detection                                                  */
/* ------------------------------------------------------------------ */
static int is_branch(uint8_t op)
{
    return op == OP_if_false || op == OP_if_true ||
           op == OP_goto_op  || op == OP_catch;
}

/* ------------------------------------------------------------------ */
/*  main                                                              */
/* ------------------------------------------------------------------ */
int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <file.bc>\n", argv[0]);
        return 2;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "error: cannot open '%s'\n", argv[1]);
        return 2;
    }

    fseek(f, 0, SEEK_END);
    long flen = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (flen < 12) {
        fprintf(stderr, "error: file too small for header\n");
        fclose(f);
        return 2;
    }

    uint8_t *data = malloc((size_t)flen);
    if (fread(data, 1, (size_t)flen, f) != (size_t)flen) {
        fprintf(stderr, "error: short read\n");
        free(data);
        fclose(f);
        return 2;
    }
    fclose(f);

    /* validate magic */
    if (data[0] != 'B' || data[1] != 'C' ||
        data[2] != 'V' || data[3] != 'F') {
        fprintf(stderr, "error: bad magic number\n");
        free(data);
        return 2;
    }

    uint16_t num_locals = (uint16_t)(data[4] | (data[5] << 8));
    uint16_t num_args   = (uint16_t)(data[6] | (data[7] << 8));
    uint32_t code_len   = (uint32_t)data[8]         | ((uint32_t)data[9]  << 8) |
                          ((uint32_t)data[10] << 16) | ((uint32_t)data[11] << 24);

    if (12 + code_len > (uint32_t)flen) {
        fprintf(stderr, "error: code_len %u exceeds file size\n", code_len);
        free(data);
        return 2;
    }

    const uint8_t *code = data + 12;

    printf("; BCVF num_locals=%u num_args=%u code_len=%u\n",
           num_locals, num_args, code_len);

    size_t pc = 0;
    int count = 0;

    while (pc < code_len) {
        uint8_t op = code[pc];
        if (op >= OP_COUNT || op == OP_invalid) {
            fprintf(stderr, "error: invalid opcode 0x%02x at offset %zu\n",
                    op, pc);
            free(data);
            return 1;
        }

        int sz = opcode_table[op].size;
        if (pc + (size_t)sz > code_len) {
            fprintf(stderr, "error: truncated instruction at offset %zu\n", pc);
            free(data);
            return 1;
        }

        printf("%d: %s", (int)pc, opcode_table[op].name);

        if (sz == 3) {
            /* 2-byte operand (u16) for locals, args, call arg_count */
            uint16_t operand = (uint16_t)((uint16_t)code[pc + 1] << 8 | code[pc + 2]);
            printf(" %u", operand);
        } else if (sz == 5) {
            int32_t operand = read_i32(code + pc + 1);
            printf(" %d", operand);

            if (is_branch(op)) {
                /* print resolved target address */
                int target = operand;
                printf(" -> %d", target);
            }
        }

        printf("\n");
        pc += (size_t)sz;
        count++;
    }

    printf("; SUMMARY instructions=%d code_bytes=%u\n", count, code_len);

    free(data);
    return 0;
}
