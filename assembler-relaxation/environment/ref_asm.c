/*
 * Reference assembler for a simplified x86-like ISA.
 * Performs jump relaxation and emits assembled binary or JSON.
 *
 * Usage: reference_asm [OPTIONS] <assembly_file>
 *   -o FILE  Write assembled binary to FILE
 *   -j       Print label/size JSON to stdout
 *   -l       Print label positions to stdout
 *   -x       Print hex dump of assembled binary to stdout
 *   -h       Show this help message
 *
 * Default (no flags): print label/size JSON to stdout
 *
 * Compiled during Docker build; source deleted from final image.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdint.h>

#define MAX_ELEMS 65536
#define MAX_LINE  1024

/* ---- opcode table ---- */
#define OP_NOP      0x00
#define OP_RET      0x01
#define OP_PUSH     0x10
#define OP_POP      0x11
#define OP_MOV_RR   0x20
#define OP_MOV_RI   0x21
#define OP_ADD_RR   0x22
#define OP_ADD_RI   0x23
#define OP_SUB_RR   0x24
#define OP_SUB_RI   0x25
#define OP_CMP_RR   0x26
#define OP_CMP_RI   0x27
#define OP_CALL     0x30

#define OP_JMP_S    0xE0
#define OP_JZ_S     0xE1
#define OP_JNZ_S    0xE2
#define OP_JL_S     0xE3
#define OP_JG_S     0xE4
#define OP_JLE_S    0xE5
#define OP_JGE_S    0xE6

#define OP_JMP_L    0xF0
#define OP_JCC_PFX  0x0F
#define OP_JZ_L2    0x81
#define OP_JNZ_L2   0x82
#define OP_JL_L2    0x83
#define OP_JG_L2    0x84
#define OP_JLE_L2   0x85
#define OP_JGE_L2   0x86

#define PAD_BYTE    0x00

/* ---- data structures ---- */
typedef enum { T_LABEL, T_FIXED, T_CALL, T_JUMP, T_ALIGN, T_FILL } EType;

typedef struct {
    EType type;
    char  name[128];
    char  mnem[16];
    int   size;
    int   is_jmp;
    int   relaxed;
    int   reg1, reg2;
    int   imm;
} Elem;

static Elem elems[MAX_ELEMS];
static int  n_elems;

typedef struct { char name[128]; int offset; } LabelEnt;
static LabelEnt ltab[MAX_ELEMS];
static int      n_labels;

static int offsets[MAX_ELEMS + 1];

/* ---- helpers ---- */

static int parse_reg(const char *s) {
    if (s[0] == 'r' && s[1] >= '0' && s[1] <= '7' && s[2] == '\0')
        return s[1] - '0';
    return -1;
}

static void str_lower(char *s) {
    for (; *s; s++) *s = (char)tolower((unsigned char)*s);
}

static char *trim(char *s) {
    while (*s && isspace((unsigned char)*s)) s++;
    char *e = s + strlen(s);
    while (e > s && isspace((unsigned char)e[-1])) e--;
    *e = '\0';
    return s;
}

static int jump_cur_size(const Elem *e) {
    if (!e->relaxed) return 2;
    return e->is_jmp ? 5 : 6;
}

/* ---- parse one line ---- */

static void parse_line(char *raw) {
    char *h = strchr(raw, '#');
    if (h) *h = '\0';
    char *line = trim(raw);
    if (!*line) return;

    int len = (int)strlen(line);

    /* label */
    if (line[len - 1] == ':') {
        int sp = 0;
        for (int i = 0; i < len - 1; i++)
            if (isspace((unsigned char)line[i])) { sp = 1; break; }
        if (!sp) {
            Elem *e  = &elems[n_elems++];
            e->type  = T_LABEL;
            memcpy(e->name, line, (size_t)(len - 1));
            e->name[len - 1] = '\0';
            e->reg1 = -1; e->reg2 = -1;
            return;
        }
    }

    char mnem[32] = "", rest[MAX_LINE] = "";
    sscanf(line, "%31s %[^\n]", mnem, rest);
    str_lower(mnem);

    /* directives */
    if (strcmp(mnem, ".align") == 0) {
        Elem *e = &elems[n_elems++];
        e->type = T_ALIGN; e->size = atoi(trim(rest));
        e->reg1 = -1; e->reg2 = -1;
        return;
    }
    if (strcmp(mnem, ".fill") == 0) {
        Elem *e = &elems[n_elems++];
        e->type = T_FILL; e->size = atoi(trim(rest));
        e->reg1 = -1; e->reg2 = -1;
        return;
    }

    /* jumps */
    static const char *jcc[] = {"jz","jnz","jl","jg","jle","jge",NULL};
    if (strcmp(mnem, "jmp") == 0) {
        Elem *e = &elems[n_elems++];
        e->type = T_JUMP; e->is_jmp = 1; e->relaxed = 0;
        strncpy(e->name, trim(rest), 127);
        strncpy(e->mnem, mnem, 15);
        e->reg1 = -1; e->reg2 = -1;
        return;
    }
    for (const char **jp = jcc; *jp; jp++) {
        if (strcmp(mnem, *jp) == 0) {
            Elem *e = &elems[n_elems++];
            e->type = T_JUMP; e->is_jmp = 0; e->relaxed = 0;
            strncpy(e->name, trim(rest), 127);
            strncpy(e->mnem, mnem, 15);
            e->reg1 = -1; e->reg2 = -1;
            return;
        }
    }

    /* call */
    if (strcmp(mnem, "call") == 0) {
        Elem *e = &elems[n_elems++];
        e->type = T_CALL;
        strncpy(e->name, trim(rest), 127);
        strncpy(e->mnem, mnem, 15);
        e->size = 5;
        e->reg1 = -1; e->reg2 = -1;
        return;
    }

    /* fixed-size instructions */
    Elem *e = &elems[n_elems++];
    e->type = T_FIXED;
    strncpy(e->mnem, mnem, 15);
    e->reg1 = -1; e->reg2 = -1; e->imm = 0;

    if (strcmp(mnem, "nop") == 0 || strcmp(mnem, "ret") == 0) {
        e->size = 1;
    } else if (strcmp(mnem, "push") == 0) {
        e->size = 2;
        e->reg1 = parse_reg(trim(rest));
    } else if (strcmp(mnem, "pop") == 0) {
        e->size = 2;
        e->reg1 = parse_reg(trim(rest));
    } else if (strcmp(mnem, "mov") == 0 || strcmp(mnem, "add") == 0 ||
               strcmp(mnem, "sub") == 0 || strcmp(mnem, "cmp") == 0) {
        char *comma = strchr(rest, ',');
        if (comma) {
            *comma = '\0';
            char *op1 = trim(rest);
            char *op2 = trim(comma + 1);
            e->reg1 = parse_reg(op1);
            int r2 = parse_reg(op2);
            if (r2 >= 0) {
                e->size = 2;
                e->reg2 = r2;
            } else {
                e->size = 3;
                e->imm = atoi(op2);
            }
        } else {
            e->size = 2;
        }
    } else {
        fprintf(stderr, "ref_asm: unknown mnemonic '%s'\n", mnem);
        exit(1);
    }
}

/* ---- layout ---- */

static void compute_layout(void) {
    n_labels = 0;
    int off = 0;
    for (int i = 0; i < n_elems; i++) {
        offsets[i] = off;
        Elem *e = &elems[i];
        switch (e->type) {
        case T_LABEL:
            strncpy(ltab[n_labels].name, e->name, 127);
            ltab[n_labels].offset = off;
            n_labels++;
            break;
        case T_FIXED: off += e->size; break;
        case T_CALL:  off += 5; break;
        case T_JUMP:  off += jump_cur_size(e); break;
        case T_ALIGN: { int n = e->size; off += (n - (off % n)) % n; break; }
        case T_FILL:  off += e->size; break;
        }
    }
    offsets[n_elems] = off;
}

static int find_label(const char *nm) {
    for (int i = 0; i < n_labels; i++)
        if (strcmp(ltab[i].name, nm) == 0) return ltab[i].offset;
    fprintf(stderr, "ref_asm: undefined label '%s'\n", nm);
    exit(1);
}

/* ---- relaxation ---- */

static void do_relax(void) {
    for (int iter = 0; iter < 500; iter++) {
        compute_layout();
        int changed = 0;
        for (int i = 0; i < n_elems; i++) {
            Elem *e = &elems[i];
            if (e->type != T_JUMP || e->relaxed) continue;
            int iend  = offsets[i] + jump_cur_size(e);
            int tgt   = find_label(e->name);
            int delta = tgt - iend;
            if (delta < -128 || delta > 127) {
                e->relaxed = 1;
                changed = 1;
            }
        }
        if (!changed) break;
    }
    compute_layout();
}

/* ---- binary emission ---- */

static void write_le32(FILE *out, int32_t val) {
    fputc((val      ) & 0xFF, out);
    fputc((val >>  8) & 0xFF, out);
    fputc((val >> 16) & 0xFF, out);
    fputc((val >> 24) & 0xFF, out);
}

static int jcc_short_op(const char *m) {
    if (strcmp(m,"jz")==0)  return OP_JZ_S;
    if (strcmp(m,"jnz")==0) return OP_JNZ_S;
    if (strcmp(m,"jl")==0)  return OP_JL_S;
    if (strcmp(m,"jg")==0)  return OP_JG_S;
    if (strcmp(m,"jle")==0) return OP_JLE_S;
    if (strcmp(m,"jge")==0) return OP_JGE_S;
    return -1;
}

static int jcc_long_op2(const char *m) {
    if (strcmp(m,"jz")==0)  return OP_JZ_L2;
    if (strcmp(m,"jnz")==0) return OP_JNZ_L2;
    if (strcmp(m,"jl")==0)  return OP_JL_L2;
    if (strcmp(m,"jg")==0)  return OP_JG_L2;
    if (strcmp(m,"jle")==0) return OP_JLE_L2;
    if (strcmp(m,"jge")==0) return OP_JGE_L2;
    return -1;
}

static void emit_all(FILE *out) {
    for (int i = 0; i < n_elems; i++) {
        Elem *e = &elems[i];
        switch (e->type) {
        case T_LABEL: break;

        case T_FIXED:
            if (strcmp(e->mnem, "nop") == 0) {
                fputc(OP_NOP, out);
            } else if (strcmp(e->mnem, "ret") == 0) {
                fputc(OP_RET, out);
            } else if (strcmp(e->mnem, "push") == 0) {
                fputc(OP_PUSH, out);
                fputc(e->reg1 & 0xFF, out);
            } else if (strcmp(e->mnem, "pop") == 0) {
                fputc(OP_POP, out);
                fputc(e->reg1 & 0xFF, out);
            } else if (strcmp(e->mnem, "mov") == 0) {
                if (e->reg2 >= 0) {
                    fputc(OP_MOV_RR, out);
                    fputc((e->reg1 << 4) | e->reg2, out);
                } else {
                    fputc(OP_MOV_RI, out);
                    fputc(e->reg1 & 0xFF, out);
                    fputc(e->imm & 0xFF, out);
                }
            } else if (strcmp(e->mnem, "add") == 0) {
                if (e->reg2 >= 0) {
                    fputc(OP_ADD_RR, out);
                    fputc((e->reg1 << 4) | e->reg2, out);
                } else {
                    fputc(OP_ADD_RI, out);
                    fputc(e->reg1 & 0xFF, out);
                    fputc(e->imm & 0xFF, out);
                }
            } else if (strcmp(e->mnem, "sub") == 0) {
                if (e->reg2 >= 0) {
                    fputc(OP_SUB_RR, out);
                    fputc((e->reg1 << 4) | e->reg2, out);
                } else {
                    fputc(OP_SUB_RI, out);
                    fputc(e->reg1 & 0xFF, out);
                    fputc(e->imm & 0xFF, out);
                }
            } else if (strcmp(e->mnem, "cmp") == 0) {
                if (e->reg2 >= 0) {
                    fputc(OP_CMP_RR, out);
                    fputc((e->reg1 << 4) | e->reg2, out);
                } else {
                    fputc(OP_CMP_RI, out);
                    fputc(e->reg1 & 0xFF, out);
                    fputc(e->imm & 0xFF, out);
                }
            }
            break;

        case T_CALL: {
            int tgt = find_label(e->name);
            int32_t rel = tgt - (offsets[i] + 5);
            fputc(OP_CALL, out);
            write_le32(out, rel);
            break;
        }

        case T_JUMP: {
            int tgt = find_label(e->name);
            int cur_sz = jump_cur_size(e);
            int32_t rel = tgt - (offsets[i] + cur_sz);
            if (!e->relaxed) {
                if (e->is_jmp)
                    fputc(OP_JMP_S, out);
                else
                    fputc(jcc_short_op(e->mnem), out);
                fputc(rel & 0xFF, out);
            } else {
                if (e->is_jmp) {
                    fputc(OP_JMP_L, out);
                    write_le32(out, rel);
                } else {
                    fputc(OP_JCC_PFX, out);
                    fputc(jcc_long_op2(e->mnem), out);
                    write_le32(out, rel);
                }
            }
            break;
        }

        case T_ALIGN: {
            int n = e->size;
            int off = offsets[i];
            int pad = (n - (off % n)) % n;
            for (int j = 0; j < pad; j++) fputc(PAD_BYTE, out);
            break;
        }

        case T_FILL:
            for (int j = 0; j < e->size; j++) fputc(PAD_BYTE, out);
            break;
        }
    }
}

/* ---- hex dump ---- */

static void hex_dump(FILE *outf, const uint8_t *buf, int len) {
    for (int i = 0; i < len; i += 16) {
        fprintf(outf, "%08x  ", i);
        for (int j = 0; j < 16; j++) {
            if (i + j < len) fprintf(outf, "%02x ", buf[i+j]);
            else             fprintf(outf, "   ");
            if (j == 7) fputc(' ', outf);
        }
        fprintf(outf, " |");
        for (int j = 0; j < 16 && i+j < len; j++) {
            int c = buf[i+j];
            fputc(isprint(c) ? c : '.', outf);
        }
        fprintf(outf, "|\n");
    }
}

/* ---- main ---- */

static void print_help(const char *prog) {
    fprintf(stderr, "Usage: %s [OPTIONS] <assembly_file>\n", prog);
    fprintf(stderr, "Options:\n");
    fprintf(stderr, "  -o FILE  Write assembled binary to FILE\n");
    fprintf(stderr, "  -j       Print label/size JSON to stdout\n");
    fprintf(stderr, "  -l       Print label positions to stdout (name offset)\n");
    fprintf(stderr, "  -x       Print hex dump of assembled binary to stdout\n");
    fprintf(stderr, "  -h       Show this help message\n");
    fprintf(stderr, "\nDefault (no flags): print label/size JSON\n");
}

int main(int argc, char *argv[]) {
    int mode_json = 0, mode_hex = 0, mode_labels = 0;
    char *out_file = NULL;
    char *asm_file = NULL;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-j") == 0) mode_json = 1;
        else if (strcmp(argv[i], "-x") == 0) mode_hex = 1;
        else if (strcmp(argv[i], "-l") == 0) mode_labels = 1;
        else if (strcmp(argv[i], "-o") == 0 && i+1 < argc) out_file = argv[++i];
        else if (strcmp(argv[i], "-h") == 0) { print_help(argv[0]); return 0; }
        else if (argv[i][0] == '-') {
            fprintf(stderr, "Unknown flag: %s\n", argv[i]); return 1;
        }
        else asm_file = argv[i];
    }

    if (!asm_file) { print_help(argv[0]); return 1; }

    FILE *f = fopen(asm_file, "r");
    if (!f) { fprintf(stderr, "Cannot open '%s'\n", asm_file); return 1; }

    char buf[MAX_LINE];
    while (fgets(buf, sizeof buf, f)) parse_line(buf);
    fclose(f);

    do_relax();

    int any_output = mode_json || mode_hex || mode_labels || (out_file != NULL);
    if (!any_output) mode_json = 1;

    if (mode_json) {
        printf("{\n  \"labels\": {\n");
        for (int i = 0; i < n_labels; i++) {
            printf("    \"%s\": %d%s\n",
                   ltab[i].name, ltab[i].offset,
                   i < n_labels - 1 ? "," : "");
        }
        printf("  },\n  \"total_size\": %d\n}\n", offsets[n_elems]);
    }

    if (mode_labels) {
        for (int i = 0; i < n_labels; i++)
            printf("%s %d\n", ltab[i].name, ltab[i].offset);
    }

    if (out_file) {
        FILE *fo = fopen(out_file, "wb");
        if (!fo) { fprintf(stderr, "Cannot create '%s'\n", out_file); return 1; }
        emit_all(fo);
        fclose(fo);
    }

    if (mode_hex) {
        int total = offsets[n_elems];
        FILE *tmp = tmpfile();
        if (!tmp) { fprintf(stderr, "tmpfile() failed\n"); return 1; }
        emit_all(tmp);
        uint8_t *mem = (uint8_t *)malloc(total);
        if (!mem) { fprintf(stderr, "malloc failed\n"); fclose(tmp); return 1; }
        rewind(tmp);
        if (total > 0) {
            size_t rd = fread(mem, 1, total, tmp);
            (void)rd;
        }
        fclose(tmp);
        hex_dump(stdout, mem, total);
        free(mem);
    }

    return 0;
}
