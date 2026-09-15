/*
 * dwarf_line.c - DWARF .debug_line section decoder
 *
 * Reads raw .debug_line section data and outputs the decoded line number matrix.
 * Supports DWARF version 2, 3, and 4 line number programs (32-bit DWARF format).
 *
 * Usage: ./dwarf_line <debug_line_file> [address_size]
 *   debug_line_file: path to raw .debug_line section data
 *   address_size:    target address size in bytes (default: 8)
 *
 * Output format (one line per matrix row, space-separated fields):
 *   0x{ADDR} LINE COL IS_STMT END_SEQ PROLOGUE_END EPILOGUE_BEGIN DISCRIM FILENAME
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdbool.h>

/* Standard opcodes (DW_LNS) */
#define DW_LNS_copy                 1
#define DW_LNS_advance_pc           2
#define DW_LNS_advance_line         3
#define DW_LNS_set_file             4
#define DW_LNS_set_column           5
#define DW_LNS_negate_stmt          6
#define DW_LNS_set_basic_block      7
#define DW_LNS_const_add_pc         8
#define DW_LNS_fixed_advance_pc     9
#define DW_LNS_set_prologue_end    10
#define DW_LNS_set_epilogue_begin  11
#define DW_LNS_set_isa            12

/* Extended opcodes (DW_LNE) */
#define DW_LNE_end_sequence         1
#define DW_LNE_set_address          2
#define DW_LNE_define_file          3
#define DW_LNE_set_discriminator    4

#define MAX_FILES 256
#define MAX_DIRS  64

typedef struct {
    uint64_t address;
    uint32_t op_index;
    uint32_t file;
    int32_t  line;
    uint32_t column;
    bool     is_stmt;
    bool     basic_block;
    bool     end_sequence;
    bool     prologue_end;
    bool     epilogue_begin;
    uint32_t isa;
    uint32_t discriminator;
} LineState;

typedef struct {
    uint64_t unit_length;
    uint16_t version;
    uint64_t header_length;
    uint8_t  min_insn_length;
    uint8_t  max_ops_per_insn;
    uint8_t  default_is_stmt;
    int8_t   line_base;
    uint8_t  line_range;
    uint8_t  opcode_base;
    uint8_t  std_opcode_lengths[256];
    const char *directories[MAX_DIRS];
    int         num_dirs;
    const char *file_names[MAX_FILES];
    uint64_t    file_dir_index[MAX_FILES];
    int         num_files;
} LineHeader;

/* ---------- primitive readers ---------- */

static uint8_t read_u8(const uint8_t **p, const uint8_t *end)
{
    if (*p >= end) { fprintf(stderr, "error: unexpected end of data\n"); exit(1); }
    return *(*p)++;
}

static uint16_t read_u16(const uint8_t **p, const uint8_t *end)
{
    if (*p + 2 > end) { fprintf(stderr, "error: unexpected end of data\n"); exit(1); }
    uint16_t v = (uint16_t)(*p)[0] | ((uint16_t)(*p)[1] << 8);
    *p += 2;
    return v;
}

static uint32_t read_u32(const uint8_t **p, const uint8_t *end)
{
    if (*p + 4 > end) { fprintf(stderr, "error: unexpected end of data\n"); exit(1); }
    uint32_t v = (uint32_t)(*p)[0] | ((uint32_t)(*p)[1] << 8) |
                 ((uint32_t)(*p)[2] << 16) | ((uint32_t)(*p)[3] << 24);
    *p += 4;
    return v;
}

static uint64_t read_u64(const uint8_t **p, const uint8_t *end)
{
    uint64_t lo = read_u32(p, end);
    uint64_t hi = read_u32(p, end);
    return lo | (hi << 32);
}

static uint64_t read_address(const uint8_t **p, const uint8_t *end, int addr_size)
{
    if (addr_size == 4) return read_u32(p, end);
    if (addr_size == 8) return read_u64(p, end);
    fprintf(stderr, "error: unsupported address size %d\n", addr_size);
    exit(1);
}

static uint64_t read_uleb128(const uint8_t **p, const uint8_t *end)
{
    uint64_t result = 0;
    unsigned shift = 0;
    uint8_t byte;
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
    int64_t result = 0;
    unsigned shift = 0;
    uint8_t byte;
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

/* ---------- state machine ---------- */

static void init_state(LineState *s, uint8_t default_is_stmt)
{
    s->address       = 0;
    s->op_index      = 0;
    s->file          = 1;
    s->line          = 1;
    s->column        = 0;
    s->is_stmt       = default_is_stmt ? true : false;
    s->basic_block   = false;
    s->end_sequence  = false;
    s->prologue_end  = false;
    s->epilogue_begin = false;
    s->isa           = 0;
    s->discriminator = 0;
}

static void emit_row(const LineState *s, const LineHeader *h, FILE *out)
{
    const char *fname = "??";
    if (s->file >= 1 && s->file <= (uint32_t)h->num_files)
        fname = h->file_names[s->file - 1];

    fprintf(out, "0x%016llx %d %u %u %u %u %u %u %s\n",
            (unsigned long long)s->address,
            (int)s->line,
            s->column,
            s->is_stmt       ? 1u : 0u,
            s->end_sequence  ? 1u : 0u,
            s->prologue_end  ? 1u : 0u,
            s->epilogue_begin ? 1u : 0u,
            s->discriminator,
            fname);
}

/* ---------- header parsing ---------- */

static int parse_header(const uint8_t **p, const uint8_t *end,
                        LineHeader *h, const uint8_t **prog_start,
                        const uint8_t **unit_end)
{
    memset(h, 0, sizeof(*h));

    uint32_t initial_length = read_u32(p, end);
    int dwarf64 = 0;
    if (initial_length == 0xffffffff) {
        h->unit_length = read_u64(p, end);
        dwarf64 = 1;
    } else {
        h->unit_length = initial_length;
    }
    *unit_end = *p + h->unit_length;

    h->version = read_u16(p, end);
    if (h->version < 2 || h->version > 4) {
        fprintf(stderr, "error: unsupported line table version %u\n", h->version);
        return -1;
    }

    h->header_length = dwarf64 ? read_u64(p, end) : read_u32(p, end);
    const uint8_t *hdr_end = *p + h->header_length;

    h->min_insn_length = read_u8(p, end);
    if (h->version >= 4)
        h->max_ops_per_insn = read_u8(p, end);
    else
        h->max_ops_per_insn = 1;

    h->default_is_stmt = read_u8(p, end);
    h->line_base       = (int8_t)read_u8(p, end);
    h->line_range       = read_u8(p, end);
    h->opcode_base      = read_u8(p, end);

    for (int i = 1; i < h->opcode_base; i++)
        h->std_opcode_lengths[i] = read_u8(p, end);

    /* include directories (sequence of null-terminated strings, then empty) */
    h->num_dirs = 0;
    while (*p < hdr_end && **p != 0) {
        if (h->num_dirs < MAX_DIRS)
            h->directories[h->num_dirs++] = (const char *)*p;
        while (*p < hdr_end && **p) (*p)++;
        (*p)++;
    }
    if (*p < hdr_end) (*p)++;   /* skip terminating null byte */

    /* file name entries: name, dir_index(uleb), mtime(uleb), length(uleb) */
    h->num_files = 0;
    while (*p < hdr_end && **p != 0) {
        const char *name = (const char *)*p;
        while (*p < hdr_end && **p) (*p)++;
        (*p)++;

        uint64_t dir_index = read_uleb128(p, hdr_end);
        read_uleb128(p, hdr_end);   /* modification time */

        if (h->num_files < MAX_FILES) {
            h->file_names[h->num_files]    = name;
            h->file_dir_index[h->num_files] = dir_index;
            h->num_files++;
        }
    }
    if (*p < hdr_end) (*p)++;

    *prog_start = hdr_end;
    *p = hdr_end;
    return 0;
}

/* ---------- line program execution ---------- */

static int run_line_program(const uint8_t **p, const uint8_t *end,
                            int addr_size, FILE *out)
{
    LineHeader hdr;
    const uint8_t *prog_start, *unit_end;

    if (parse_header(p, end, &hdr, &prog_start, &unit_end) < 0)
        return -1;
    *p = prog_start;

    LineState state;
    init_state(&state, hdr.default_is_stmt);

    while (*p < unit_end) {
        uint8_t op = read_u8(p, unit_end);

        if (op == 0) {
            /* ---- extended opcode ---- */
            uint64_t ext_len = read_uleb128(p, unit_end);
            const uint8_t *ext_end = *p + ext_len;
            uint8_t sub = read_u8(p, unit_end);

            switch (sub) {
            case DW_LNE_end_sequence:
                state.end_sequence = true;
                emit_row(&state, &hdr, out);
                state.address       = 0;
                state.line          = 1;
                state.column        = 0;
                state.is_stmt       = hdr.default_is_stmt ? true : false;
                state.basic_block   = false;
                state.end_sequence  = false;
                state.prologue_end  = false;
                state.epilogue_begin = false;
                state.isa           = 0;
                state.discriminator = 0;
                break;

            case DW_LNE_set_address:
                state.address  = read_address(p, unit_end, addr_size);
                state.op_index = 0;
                break;

            case DW_LNE_define_file: {
                const char *fn = (const char *)*p;
                while (*p < ext_end && **p) (*p)++;
                (*p)++;
                uint64_t di = read_uleb128(p, ext_end);
                read_uleb128(p, ext_end);   /* mtime  */
                read_uleb128(p, ext_end);   /* length */
                if (hdr.num_files < MAX_FILES) {
                    hdr.file_names[hdr.num_files]    = fn;
                    hdr.file_dir_index[hdr.num_files] = di;
                    hdr.num_files++;
                }
                break;
            }

            case DW_LNE_set_discriminator:
                state.discriminator = (uint32_t)read_uleb128(p, unit_end);
                break;

            default:
                break;
            }
            *p = ext_end;

        } else if (op < hdr.opcode_base) {
            /* ---- standard opcode ---- */
            switch (op) {
            case DW_LNS_copy:
                emit_row(&state, &hdr, out);
                state.discriminator  = 0;
                state.basic_block    = false;
                state.prologue_end   = false;
                state.epilogue_begin = false;
                break;

            case DW_LNS_advance_pc: {
                uint64_t adv = read_uleb128(p, unit_end);
                state.address += hdr.min_insn_length *
                    ((state.op_index + adv) / hdr.max_ops_per_insn);
                state.op_index =
                    (state.op_index + (uint32_t)adv) % hdr.max_ops_per_insn;
                break;
            }

            case DW_LNS_advance_line:
                state.line += (int32_t)read_sleb128(p, unit_end);
                break;

            case DW_LNS_set_file:
                state.file = (uint32_t)read_uleb128(p, unit_end);
                break;

            case DW_LNS_set_column:
                state.column = (uint32_t)read_uleb128(p, unit_end);
                break;

            case DW_LNS_negate_stmt:
                state.is_stmt = !state.is_stmt;
                break;

            case DW_LNS_set_basic_block:
                state.basic_block = true;
                break;

            case DW_LNS_fixed_advance_pc: {
                uint16_t adv = read_u16(p, unit_end);
                state.address += adv;
                state.op_index = 0;
                break;
            }

            case DW_LNS_set_prologue_end:
                state.prologue_end = true;
                break;

            case DW_LNS_set_epilogue_begin:
                state.epilogue_begin = true;
                break;

            case DW_LNS_set_isa:
                state.isa = (uint32_t)read_uleb128(p, unit_end);
                break;

            default:
                /* unknown standard opcode -- skip its operands */
                for (int i = 0; i < hdr.std_opcode_lengths[op]; i++)
                    read_uleb128(p, unit_end);
                break;
            }

        } else {
            /* ---- special opcode ---- */
            int adjusted = op - hdr.opcode_base;

            int line_inc   = hdr.line_base + (adjusted / hdr.line_range);
            int op_advance = adjusted % hdr.line_range;

            state.address += hdr.min_insn_length *
                ((state.op_index + op_advance) / hdr.max_ops_per_insn);
            state.op_index =
                (state.op_index + op_advance) % hdr.max_ops_per_insn;
            state.line += line_inc;

            emit_row(&state, &hdr, out);

            state.basic_block    = false;
            state.prologue_end   = false;
            state.epilogue_begin = false;
            state.discriminator  = 0;
        }
    }
    return 0;
}

/* ---------- main ---------- */

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <debug_line_file> [address_size]\n", argv[0]);
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

    const uint8_t *ptr = buf;
    const uint8_t *end = buf + sz;

    while (ptr < end) {
        if (run_line_program(&ptr, end, addr_size, stdout) < 0) {
            fprintf(stderr, "error: failed to decode line program\n");
            break;
        }
    }

    free(buf);
    return 0;
}
