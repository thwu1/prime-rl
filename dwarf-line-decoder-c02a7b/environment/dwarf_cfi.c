/*
 * dwarf_cfi.c - DWARF .debug_frame Call Frame Information decoder
 *
 * Reads raw .debug_frame section data and outputs decoded CIE/FDE entries
 * with register rule tables at each code location.
 *
 * Usage: ./dwarf_cfi <debug_frame_file> [address_size]
 *   debug_frame_file: path to raw .debug_frame section data
 *   address_size:     target address size in bytes (default: 8)
 *
 * Output format:
 *   CIE @<hex>: v=<ver> ca=<code_align> da=<data_align> ret=<reg> aug="<str>"
 *     [initial] cfa=r<N>+<off> {r<M>=[cfa+<off>] ...}
 *   FDE @<hex>: pc=[<hex_lo>,<hex_hi>) cie=@<hex>
 *     [<hex_addr>] cfa=r<N>+<off> {r<M>=[cfa+<off>] ...}
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdbool.h>

/* DW_CFA instructions - high 2 bits are primary opcode */
#define DW_CFA_advance_loc_hi     0x01  /* high2 bits = 01 */
#define DW_CFA_offset_hi          0x02  /* high2 bits = 10 */
#define DW_CFA_restore_hi         0x03  /* high2 bits = 11 */

/* DW_CFA instructions with opcode in full byte (high 2 bits = 00) */
#define DW_CFA_nop                0x00
#define DW_CFA_set_loc            0x01
#define DW_CFA_advance_loc1       0x02
#define DW_CFA_advance_loc2       0x03
#define DW_CFA_advance_loc4       0x04
#define DW_CFA_offset_extended    0x05
#define DW_CFA_restore_extended   0x06
#define DW_CFA_undefined          0x07
#define DW_CFA_same_value         0x08
#define DW_CFA_register           0x09
#define DW_CFA_remember_state     0x0a
#define DW_CFA_restore_state      0x0b
#define DW_CFA_def_cfa            0x0c
#define DW_CFA_def_cfa_register   0x0d
#define DW_CFA_def_cfa_offset     0x0e
#define DW_CFA_def_cfa_expression 0x0f
#define DW_CFA_expression         0x10
#define DW_CFA_offset_extended_sf 0x11
#define DW_CFA_def_cfa_sf         0x12
#define DW_CFA_def_cfa_offset_sf  0x13
#define DW_CFA_val_offset         0x14
#define DW_CFA_val_offset_sf      0x15
#define DW_CFA_val_expression     0x16

#define MAX_REGS  128
#define MAX_STACK 16
#define MAX_CIES  64

/* ---------- data types ---------- */

typedef enum {
    RULE_UNDEFINED = 0,
    RULE_SAME_VALUE,
    RULE_OFFSET,
    RULE_VAL_OFFSET,
    RULE_REGISTER,
    RULE_EXPRESSION,
    RULE_VAL_EXPRESSION
} RuleType;

typedef struct {
    RuleType type;
    int64_t  operand;  /* offset for OFFSET/VAL_OFFSET, register for REGISTER */
} RegRule;

typedef struct {
    uint32_t reg;
    int64_t  offset;
    bool     is_expr;
} CfaRule;

typedef struct {
    CfaRule cfa;
    RegRule regs[MAX_REGS];
} RuleRow;

typedef struct {
    RuleRow rows[MAX_STACK];
    int     count;
    int     read_pos;  /* front pointer for queue behavior */
} StateStack;

typedef struct {
    uint64_t    offset;
    uint8_t     version;
    char        augmentation[64];
    uint64_t    code_alignment_factor;
    int64_t     data_alignment_factor;
    uint64_t    return_address_register;
    uint8_t     address_size;
    uint8_t     segment_selector_size;
    const uint8_t *initial_instructions;
    uint64_t    initial_instructions_len;
    RuleRow     initial_row;
} CIE;

/* ---------- globals ---------- */

static CIE  g_cies[MAX_CIES];
static int   g_num_cies = 0;

/* ---------- primitive readers ---------- */

static uint8_t read_u8(const uint8_t **p, const uint8_t *end)
{
    if (*p >= end) { fprintf(stderr, "error: unexpected end of data\n"); exit(1); }
    return *(*p)++;
}

static uint16_t read_u16(const uint8_t **p, const uint8_t *end)
{
    if (*p + 2 > end) { fprintf(stderr, "error: unexpected end\n"); exit(1); }
    uint16_t v = (uint16_t)(*p)[0] | ((uint16_t)(*p)[1] << 8);
    *p += 2;
    return v;
}

static uint32_t read_u32(const uint8_t **p, const uint8_t *end)
{
    if (*p + 4 > end) { fprintf(stderr, "error: unexpected end\n"); exit(1); }
    uint32_t v = (uint32_t)(*p)[0] | ((uint32_t)(*p)[1] << 8)
               | ((uint32_t)(*p)[2] << 16) | ((uint32_t)(*p)[3] << 24);
    *p += 4;
    return v;
}

static uint64_t read_u64(const uint8_t **p, const uint8_t *end)
{
    uint64_t lo = read_u32(p, end);
    uint64_t hi = read_u32(p, end);
    return lo | (hi << 32);
}

static uint64_t read_address(const uint8_t **p, const uint8_t *end, int addr_sz)
{
    if (addr_sz == 4) return read_u32(p, end);
    if (addr_sz == 8) return read_u64(p, end);
    fprintf(stderr, "error: unsupported address size %d\n", addr_sz);
    exit(1);
}

static uint64_t read_uleb128(const uint8_t **p, const uint8_t *end)
{
    uint64_t result = 0;
    unsigned shift  = 0;
    uint8_t  byte;
    do {
        if (*p >= end) { fprintf(stderr, "error: truncated ULEB128\n"); exit(1); }
        byte = *(*p)++;
        result |= (uint64_t)(byte & 0x7f) << shift;
        shift += 7;
    } while (byte & 0x80);
    return result;
}

static int64_t read_sleb128(const uint8_t **p, const uint8_t *end)
{
    int64_t  result = 0;
    unsigned shift  = 0;
    uint8_t  byte;
    do {
        if (*p >= end) { fprintf(stderr, "error: truncated SLEB128\n"); exit(1); }
        byte = *(*p)++;
        result |= (int64_t)(byte & 0x7f) << shift;
        shift += 7;
    } while (byte & 0x80);
    /* sign-extend negative values */
    if ((shift < 64) && (byte & 0x80)) {
        result |= -(1LL << shift);
    }
    return result;
}

/* ---------- rule table helpers ---------- */

static void init_rule_row(RuleRow *r)
{
    memset(r, 0, sizeof(*r));
    r->cfa.reg    = 0;
    r->cfa.offset = 0;
    r->cfa.is_expr = false;
    for (int i = 0; i < MAX_REGS; i++)
        r->regs[i].type = RULE_UNDEFINED;
}

static void copy_rule_row(RuleRow *dst, const RuleRow *src)
{
    memcpy(dst, src, sizeof(RuleRow));
}

static void push_state(StateStack *stk, const RuleRow *row)
{
    if (stk->count >= MAX_STACK) {
        fprintf(stderr, "warning: state stack overflow\n");
        return;
    }
    copy_rule_row(&stk->rows[stk->count], row);
    stk->count++;
}

static bool pop_state(StateStack *stk, RuleRow *row)
{
    if (stk->read_pos >= stk->count) {
        fprintf(stderr, "warning: state stack underflow\n");
        return false;
    }
    copy_rule_row(row, &stk->rows[stk->read_pos]);
    stk->read_pos++;
    return true;
}

/* ---------- output ---------- */

static void print_rule_row(FILE *out, const char *loc_str, const RuleRow *row)
{
    if (row->cfa.is_expr)
        fprintf(out, "  %s cfa=expr", loc_str);
    else
        fprintf(out, "  %s cfa=r%u%+lld", loc_str,
                row->cfa.reg, (long long)row->cfa.offset);

    bool has = false;
    for (int i = 0; i < MAX_REGS; i++)
        if (row->regs[i].type != RULE_UNDEFINED) { has = true; break; }

    if (has) {
        fprintf(out, " {");
        bool first = true;
        for (int i = 0; i < MAX_REGS; i++) {
            if (row->regs[i].type == RULE_UNDEFINED)
                continue;
            if (!first) fprintf(out, " ");
            first = false;
            switch (row->regs[i].type) {
            case RULE_SAME_VALUE:
                fprintf(out, "r%d=same", i);
                break;
            case RULE_OFFSET:
                fprintf(out, "r%d=[cfa%+lld]", i, (long long)row->regs[i].operand);
                break;
            case RULE_VAL_OFFSET:
                fprintf(out, "r%d=val(cfa%+lld)", i, (long long)row->regs[i].operand);
                break;
            case RULE_REGISTER:
                fprintf(out, "r%d=r%lld", i, (long long)row->regs[i].operand);
                break;
            case RULE_EXPRESSION:
                fprintf(out, "r%d=expr", i);
                break;
            case RULE_VAL_EXPRESSION:
                fprintf(out, "r%d=val_expr", i);
                break;
            default:
                break;
            }
        }
        fprintf(out, "}");
    }
    fprintf(out, "\n");
}

/* ---------- CFI instruction execution ---------- */

static int execute_cfi(const uint8_t *start, const uint8_t *end,
                       uint64_t code_align, int64_t data_align,
                       int addr_size,
                       RuleRow *row, StateStack *stk,
                       uint64_t *loc, FILE *out,
                       const RuleRow *cie_init,
                       bool emit)
{
    const uint8_t *p = start;

    while (p < end) {
        uint8_t op    = read_u8(&p, end);
        uint8_t high2 = op >> 6;
        uint8_t low6  = op & 0x3F;

        if (high2 == 1) {
            /* DW_CFA_advance_loc: delta in low 6 bits */
            uint64_t delta = low6;
            *loc += delta;
            if (emit) {
                char buf[40];
                snprintf(buf, sizeof(buf), "[0x%016llx]",
                         (unsigned long long)*loc);
                print_rule_row(out, buf, row);
            }

        } else if (high2 == 2) {
            /* DW_CFA_offset: register in low 6 bits, factored offset ULEB128 */
            uint64_t reg = low6;
            uint64_t factored = read_uleb128(&p, end);
            if (reg < MAX_REGS) {
                row->regs[reg].type    = RULE_OFFSET;
                row->regs[reg].operand = (int64_t)(factored * (uint64_t)code_align);
            }

        } else if (high2 == 3) {
            /* DW_CFA_restore: register in low 6 bits */
            uint64_t reg = low6;
            if (reg < MAX_REGS) {
                if (cie_init)
                    row->regs[reg] = cie_init->regs[reg];
                else
                    row->regs[reg].type = RULE_UNDEFINED;
            }

        } else {
            /* high2 == 0: full-byte opcodes */
            switch (op) {
            case DW_CFA_nop:
                break;

            case DW_CFA_set_loc:
                *loc = read_address(&p, end, addr_size);
                if (emit) {
                    char buf[40];
                    snprintf(buf, sizeof(buf), "[0x%016llx]",
                             (unsigned long long)*loc);
                    print_rule_row(out, buf, row);
                }
                break;

            case DW_CFA_advance_loc1: {
                uint8_t delta = read_u8(&p, end);
                *loc += delta;
                if (emit) {
                    char buf[40];
                    snprintf(buf, sizeof(buf), "[0x%016llx]",
                             (unsigned long long)*loc);
                    print_rule_row(out, buf, row);
                }
                break;
            }

            case DW_CFA_advance_loc2: {
                uint16_t delta = read_u16(&p, end);
                *loc += delta;
                if (emit) {
                    char buf[40];
                    snprintf(buf, sizeof(buf), "[0x%016llx]",
                             (unsigned long long)*loc);
                    print_rule_row(out, buf, row);
                }
                break;
            }

            case DW_CFA_advance_loc4: {
                uint32_t delta = read_u32(&p, end);
                *loc += delta;
                if (emit) {
                    char buf[40];
                    snprintf(buf, sizeof(buf), "[0x%016llx]",
                             (unsigned long long)*loc);
                    print_rule_row(out, buf, row);
                }
                break;
            }

            case DW_CFA_offset_extended: {
                uint64_t reg = read_uleb128(&p, end);
                uint64_t factored = read_uleb128(&p, end);
                if (reg < MAX_REGS) {
                    row->regs[reg].type    = RULE_OFFSET;
                    row->regs[reg].operand = (int64_t)(factored * (uint64_t)code_align);
                }
                break;
            }

            case DW_CFA_restore_extended: {
                uint64_t reg = read_uleb128(&p, end);
                if (reg < MAX_REGS) {
                    if (cie_init)
                        row->regs[reg] = cie_init->regs[reg];
                    else
                        row->regs[reg].type = RULE_UNDEFINED;
                }
                break;
            }

            case DW_CFA_undefined: {
                uint64_t reg = read_uleb128(&p, end);
                if (reg < MAX_REGS)
                    row->regs[reg].type = RULE_UNDEFINED;
                break;
            }

            case DW_CFA_same_value: {
                uint64_t reg = read_uleb128(&p, end);
                if (reg < MAX_REGS)
                    row->regs[reg].type = RULE_SAME_VALUE;
                break;
            }

            case DW_CFA_register: {
                uint64_t reg    = read_uleb128(&p, end);
                uint64_t target = read_uleb128(&p, end);
                if (reg < MAX_REGS) {
                    row->regs[reg].type    = RULE_REGISTER;
                    row->regs[reg].operand = (int64_t)target;
                }
                break;
            }

            case DW_CFA_remember_state:
                push_state(stk, row);
                break;

            case DW_CFA_restore_state:
                pop_state(stk, row);
                break;

            case DW_CFA_def_cfa: {
                row->cfa.reg    = (uint32_t)read_uleb128(&p, end);
                row->cfa.offset = (int64_t)read_uleb128(&p, end);
                row->cfa.is_expr = false;
                break;
            }

            case DW_CFA_def_cfa_register:
                row->cfa.reg = (uint32_t)read_uleb128(&p, end);
                break;

            case DW_CFA_def_cfa_offset:
                row->cfa.offset = (int64_t)read_uleb128(&p, end);
                break;

            case DW_CFA_def_cfa_expression: {
                uint64_t len = read_uleb128(&p, end);
                row->cfa.is_expr = true;
                p += len;
                break;
            }

            case DW_CFA_expression: {
                uint64_t reg = read_uleb128(&p, end);
                uint64_t len = read_uleb128(&p, end);
                if (reg < MAX_REGS)
                    row->regs[reg].type = RULE_EXPRESSION;
                p += len;
                break;
            }

            case DW_CFA_offset_extended_sf: {
                uint64_t reg = read_uleb128(&p, end);
                int64_t  off = read_sleb128(&p, end);
                if (reg < MAX_REGS) {
                    row->regs[reg].type    = RULE_OFFSET;
                    row->regs[reg].operand = off * (int64_t)code_align;
                }
                break;
            }

            case DW_CFA_def_cfa_sf: {
                row->cfa.reg    = (uint32_t)read_uleb128(&p, end);
                int64_t off     = read_sleb128(&p, end);
                row->cfa.offset = off;
                row->cfa.is_expr = false;
                break;
            }

            case DW_CFA_def_cfa_offset_sf: {
                int64_t off     = read_sleb128(&p, end);
                row->cfa.offset = off * data_align;
                break;
            }

            case DW_CFA_val_offset: {
                uint64_t reg = read_uleb128(&p, end);
                uint64_t factored = read_uleb128(&p, end);
                if (reg < MAX_REGS) {
                    row->regs[reg].type    = RULE_VAL_OFFSET;
                    row->regs[reg].operand = (int64_t)(factored * (uint64_t)code_align);
                }
                break;
            }

            case DW_CFA_val_offset_sf: {
                uint64_t reg = read_uleb128(&p, end);
                int64_t  off = read_sleb128(&p, end);
                if (reg < MAX_REGS) {
                    row->regs[reg].type    = RULE_VAL_OFFSET;
                    row->regs[reg].operand = off * data_align;
                }
                break;
            }

            case DW_CFA_val_expression: {
                uint64_t reg = read_uleb128(&p, end);
                uint64_t len = read_uleb128(&p, end);
                if (reg < MAX_REGS)
                    row->regs[reg].type = RULE_VAL_EXPRESSION;
                p += len;
                break;
            }

            default:
                fprintf(stderr, "warning: unknown CFI opcode 0x%02x\n", op);
                return -1;
            }
        }
    }
    return 0;
}

/* ---------- CIE lookup ---------- */

static CIE *find_cie(uint64_t offset)
{
    for (int i = 0; i < g_num_cies; i++)
        if (g_cies[i].offset == offset)
            return &g_cies[i];
    return NULL;
}

/* ---------- main decoder ---------- */

static int decode_debug_frame(const uint8_t *data, uint64_t length,
                              int default_addr_size, FILE *out)
{
    const uint8_t *p   = data;
    const uint8_t *sec = data + length;

    while (p < sec) {
        uint64_t entry_off = (uint64_t)(p - data);

        /* read entry length */
        uint32_t init_len = read_u32(&p, sec);
        int dwarf64 = 0;
        uint64_t entry_len;

        if (init_len == 0xffffffff) {
            entry_len = read_u64(&p, sec);
            dwarf64   = 1;
        } else if (init_len == 0) {
            break;  /* zero-length terminator */
        } else {
            entry_len = init_len;
        }

        const uint8_t *entry_end = p + entry_len;

        /* read CIE_id / CIE_pointer */
        uint64_t cie_id;
        if (dwarf64)
            cie_id = read_u64(&p, entry_end);
        else
            cie_id = read_u32(&p, entry_end);

        /* In .debug_frame CIE has id == 0xffffffff (32) or 0xffffffffffffffff (64) */
        bool is_cie = (cie_id == 0xffffffff);

        if (is_cie) {
            /* ===== CIE ===== */
            if (g_num_cies >= MAX_CIES) {
                fprintf(stderr, "error: too many CIEs\n");
                p = entry_end;
                continue;
            }
            CIE *cie = &g_cies[g_num_cies];
            memset(cie, 0, sizeof(CIE));
            cie->offset = entry_off;

            cie->version = read_u8(&p, entry_end);

            /* augmentation string */
            int ai = 0;
            while (p < entry_end && *p != 0) {
                if (ai < 63) cie->augmentation[ai++] = (char)*p;
                p++;
            }
            cie->augmentation[ai] = '\0';
            p++;  /* skip NUL */

            /* v4 adds address_size and segment_selector_size */
            if (cie->version >= 4) {
                cie->address_size          = read_u8(&p, entry_end);
                cie->segment_selector_size = read_u8(&p, entry_end);
            } else {
                cie->address_size          = (uint8_t)default_addr_size;
                cie->segment_selector_size = 0;
            }

            cie->code_alignment_factor  = read_uleb128(&p, entry_end);
            cie->data_alignment_factor  = read_sleb128(&p, entry_end);

            if (cie->version == 1)
                cie->return_address_register = read_u8(&p, entry_end);
            else
                cie->return_address_register = read_uleb128(&p, entry_end);

            /* augmentation data for 'z' */
            if (cie->augmentation[0] == 'z') {
                uint64_t aug_len = read_uleb128(&p, entry_end);
                /* augmentation data bytes follow -- skip them */
                (void)aug_len;
            }

            /* rest = initial instructions */
            cie->initial_instructions     = p;
            cie->initial_instructions_len = (uint64_t)(entry_end - p);

            /* print CIE header */
            fprintf(out, "CIE @0x%llx: v=%u ca=%llu da=%lld ret=%llu aug=\"%s\"\n",
                    (unsigned long long)cie->offset,
                    cie->version,
                    (unsigned long long)cie->code_alignment_factor,
                    (long long)cie->data_alignment_factor,
                    (unsigned long long)cie->return_address_register,
                    cie->augmentation);

            /* compute initial rules */
            init_rule_row(&cie->initial_row);
            {
                StateStack tmp;
                memset(&tmp, 0, sizeof(tmp));
                uint64_t tmp_loc = 0;
                execute_cfi(cie->initial_instructions,
                            cie->initial_instructions + cie->initial_instructions_len,
                            cie->code_alignment_factor,
                            cie->data_alignment_factor,
                            cie->address_size,
                            &cie->initial_row, &tmp, &tmp_loc,
                            out, NULL, false);
            }
            print_rule_row(out, "[initial]", &cie->initial_row);

            g_num_cies++;

        } else {
            /* ===== FDE ===== */
            uint64_t cie_ptr = cie_id;
            CIE *cie = find_cie(cie_ptr);
            if (!cie) {
                fprintf(stderr, "error: FDE @0x%llx refs unknown CIE @0x%llx\n",
                        (unsigned long long)entry_off,
                        (unsigned long long)cie_ptr);
                p = entry_end;
                continue;
            }

            int fde_addr_sz = cie->address_size;

            if (cie->segment_selector_size > 0)
                p += cie->segment_selector_size;

            uint64_t pc_begin = read_address(&p, entry_end, fde_addr_sz);
            uint64_t pc_range = read_address(&p, entry_end, fde_addr_sz);

            /* augmentation data for 'z' FDEs */
            if (cie->augmentation[0] == 'z') {
                uint64_t fde_aug = read_uleb128(&p, entry_end);
                p += fde_aug;
            }

            fprintf(out, "FDE @0x%llx: pc=[0x%llx,0x%llx) cie=@0x%llx\n",
                    (unsigned long long)entry_off,
                    (unsigned long long)pc_begin,
                    (unsigned long long)(pc_begin + pc_range),
                    (unsigned long long)cie_ptr);

            /* set up rule row -- start from empty, not CIE initial rules */
            RuleRow row;
            init_rule_row(&row);

            StateStack stk;
            memset(&stk, 0, sizeof(stk));

            uint64_t loc = pc_begin;

            /* print initial rule row */
            {
                char buf[40];
                snprintf(buf, sizeof(buf), "[0x%016llx]",
                         (unsigned long long)loc);
                print_rule_row(out, buf, &row);
            }

            /* execute FDE instructions */
            execute_cfi(p, entry_end,
                        cie->code_alignment_factor,
                        cie->data_alignment_factor,
                        fde_addr_sz,
                        &row, &stk, &loc, out,
                        NULL, true);
        }

        p = entry_end;
    }
    return 0;
}

/* ---------- main ---------- */

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <debug_frame_file> [address_size]\n", argv[0]);
        return 1;
    }

    int addr_size = (argc > 2) ? atoi(argv[2]) : 8;

    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }

    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);

    uint8_t *buf = malloc(sz);
    if (!buf) { perror("malloc"); fclose(f); return 1; }
    if ((long)fread(buf, 1, sz, f) != sz) {
        perror("fread"); free(buf); fclose(f); return 1;
    }
    fclose(f);

    g_num_cies = 0;
    decode_debug_frame(buf, (uint64_t)sz, addr_size, stdout);

    free(buf);
    return 0;
}
