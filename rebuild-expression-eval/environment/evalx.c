/* evalx - custom expression evaluator (reference implementation) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdint.h>
#include <inttypes.h>

enum {
    T_NUM, T_ID, T_PLUS, T_MINUS, T_MUL, T_DIV, T_MOD,
    T_AND, T_OR, T_XOR, T_NOT, T_SHL, T_SHR,
    T_POW, T_HASH, T_ROT, T_BYTE,
    T_LP, T_RP, T_COMMA, T_END, T_ERR
};

static const char *src;
static int tok;
static int64_t tok_num;
static char tok_id[64];

static int64_t expr(void);

static void advance(void) {
    while (*src == ' ' || *src == '\t') src++;
    if (!*src) { tok = T_END; return; }
    if (*src == '0' && (src[1] == 'x' || src[1] == 'X') && isxdigit(src[2])) {
        char *e; tok_num = (int64_t)strtoull(src, &e, 16); src = e; tok = T_NUM; return;
    }
    if (isdigit(*src)) {
        char *e; tok_num = strtoll(src, &e, 10); src = e; tok = T_NUM; return;
    }
    if (isalpha(*src) || *src == '_') {
        int i = 0;
        while (isalnum(*src) || *src == '_') { if (i < 63) tok_id[i++] = *src; src++; }
        tok_id[i] = 0; tok = T_ID; return;
    }
    char c = *src++;
    switch (c) {
        case '+': tok = T_PLUS; break;
        case '-': tok = T_MINUS; break;
        case '*': if (*src == '*') { src++; tok = T_POW; } else tok = T_MUL; break;
        case '/': tok = T_DIV; break;
        case '%': tok = T_MOD; break;
        case '&': tok = T_AND; break;
        case '|': tok = T_OR; break;
        case '^': tok = T_XOR; break;
        case '~': tok = T_NOT; break;
        case '<': if (*src == '<') { src++; tok = T_SHL; } else tok = T_ERR; break;
        case '>': if (*src == '>') { src++; tok = T_SHR; } else tok = T_ERR; break;
        case '#': tok = T_HASH; break;
        case '@': tok = T_ROT; break;
        case '$': tok = T_BYTE; break;
        case '(': tok = T_LP; break;
        case ')': tok = T_RP; break;
        case ',': tok = T_COMMA; break;
        default: tok = T_ERR; break;
    }
}

static uint32_t do_crc32(uint32_t v) {
    uint8_t b[4] = { v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF };
    uint32_t c = 0xFFFFFFFF;
    for (int i = 0; i < 4; i++) {
        c ^= b[i];
        for (int j = 0; j < 8; j++)
            c = (c & 1) ? (c >> 1) ^ 0xEDB88320U : c >> 1;
    }
    return c ^ 0xFFFFFFFF;
}

static const uint32_t _fk[4] = {
    0xA3B1C6D7U, 0x1F2E3D4CU, 0x5A6B7C8DU, 0xE9F0A1B2U
};

static int64_t do_cipher(uint32_t input) {
    uint16_t l = (uint16_t)(input >> 16);
    uint16_t r = (uint16_t)(input & 0xFFFF);
    for (int i = 0; i < 4; i++) {
        uint16_t klo = (uint16_t)(_fk[i] & 0xFFFF);
        uint16_t khi = (uint16_t)(_fk[i] >> 16);
        uint16_t f = (uint16_t)(((uint32_t)r * (uint32_t)klo) >> 16) ^ khi;
        uint16_t nr = l ^ f;
        l = r;
        r = nr;
    }
    return (int64_t)(((uint32_t)l << 16) | (uint32_t)r);
}

static int64_t do_func(const char *nm, int64_t *a, int n) {
    if (!strcmp(nm, "gcd") && n == 2) {
        int64_t x = a[0] < 0 ? -a[0] : a[0], y = a[1] < 0 ? -a[1] : a[1];
        while (y) { int64_t t = y; y = x % y; x = t; }
        return x;
    }
    if (!strcmp(nm, "lcm") && n == 2) {
        if (!a[0] || !a[1]) return 0;
        int64_t x = a[0] < 0 ? -a[0] : a[0], y = a[1] < 0 ? -a[1] : a[1];
        int64_t g = x, h = y;
        while (h) { int64_t t = h; h = g % h; g = t; }
        return x / g * y;
    }
    if (!strcmp(nm, "fib") && n == 1) {
        if (a[0] <= 0) return 0;
        if (a[0] == 1) return 1;
        int64_t x = 0, y = 1;
        for (int64_t i = 2; i <= a[0]; i++) { int64_t t = x + y; x = y; y = t; }
        return y;
    }
    if (!strcmp(nm, "popcount") && n == 1) {
        uint32_t v = (uint32_t)(a[0] & 0xFFFFFFFF);
        int c = 0; while (v) { c += v & 1; v >>= 1; } return c;
    }
    if (!strcmp(nm, "bitrev") && n == 1) {
        uint32_t v = (uint32_t)(a[0] & 0xFFFFFFFF), r = 0;
        for (int i = 0; i < 32; i++) { r = (r << 1) | (v & 1); v >>= 1; }
        return (int64_t)r;
    }
    if (!strcmp(nm, "crc32") && n == 1)
        return (int64_t)do_crc32((uint32_t)(a[0] & 0xFFFFFFFF));
    if (!strcmp(nm, "cipher") && n == 1)
        return do_cipher((uint32_t)(a[0] & 0xFFFFFFFF));
    if (!strcmp(nm, "abs") && n == 1)
        return a[0] < 0 ? -a[0] : a[0];
    if (!strcmp(nm, "min") && n == 2)
        return a[0] < a[1] ? a[0] : a[1];
    if (!strcmp(nm, "max") && n == 2)
        return a[0] > a[1] ? a[0] : a[1];
    fprintf(stderr, "Error: unknown function\n");
    return 0;
}

/*
 * Precedence (low to high):
 *  0: #          hash-combine
 *  1: |          bitwise or
 *  2: ^          bitwise xor
 *  3: &          bitwise and
 *  4: << >>      shifts
 *  5: + -        additive
 *  6: * / %      multiplicative
 *  7: @ $        rotate, byte-extract
 *  8: unary -    negation
 *  9: **         power (right-assoc)
 * 10: unary ~    bitwise not
 * 11: primary    literals, functions, parens
 */

static int64_t primary(void) {
    if (tok == T_NUM) { int64_t v = tok_num; advance(); return v; }
    if (tok == T_ID) {
        char name[64]; strcpy(name, tok_id); advance();
        if (tok == T_LP) {
            advance();
            int64_t args[8]; int n = 0;
            if (tok != T_RP) {
                args[n++] = expr();
                while (tok == T_COMMA && n < 8) { advance(); args[n++] = expr(); }
            }
            if (tok == T_RP) advance();
            return do_func(name, args, n);
        }
        fprintf(stderr, "Error: syntax error\n");
        return 0;
    }
    if (tok == T_LP) {
        advance(); int64_t v = expr();
        if (tok == T_RP) advance();
        return v;
    }
    fprintf(stderr, "Error: syntax error\n");
    return 0;
}

static int64_t p_unary(void) {
    if (tok == T_NOT) {
        advance(); int64_t v = p_unary();
        return (int64_t)(~((uint32_t)(v & 0xFFFFFFFF)));
    }
    return primary();
}

static int64_t p_neg(void);

static int64_t p_power(void) {
    int64_t left = p_unary();
    if (tok == T_POW) {
        advance();
        int64_t right = p_neg();
        if (right < 0) return 0;
        uint64_t r = 1, b = (uint64_t)left, e = (uint64_t)right;
        while (e) { if (e & 1) r *= b; b *= b; e >>= 1; }
        return (int64_t)r;
    }
    return left;
}

static int64_t p_neg(void) {
    if (tok == T_MINUS) {
        advance();
        return (int64_t)(-(uint64_t)p_neg());
    }
    return p_power();
}

static int64_t p_custom(void) {
    int64_t left = p_neg();
    while (tok == T_ROT || tok == T_BYTE) {
        int op = tok; advance();
        int64_t right = p_neg();
        if (op == T_ROT) {
            uint32_t v = (uint32_t)(left & 0xFFFFFFFF);
            int s = (int)(right & 31);
            left = s ? (int64_t)((v << s) | (v >> (32 - s))) : (int64_t)v;
        } else {
            uint32_t v = (uint32_t)(left & 0xFFFFFFFF);
            int idx = (int)(right & 3);
            left = (int64_t)((v >> (idx * 8)) & 0xFF);
        }
    }
    return left;
}

static int64_t p_mul(void) {
    int64_t left = p_custom();
    while (tok == T_MUL || tok == T_DIV || tok == T_MOD) {
        int op = tok; advance();
        int64_t right = p_custom();
        if (op == T_MUL) left = (int64_t)((uint64_t)left * (uint64_t)right);
        else if (right == 0) left = 0;
        else if (op == T_DIV) left = left / right;
        else left = left % right;
    }
    return left;
}

static int64_t p_add(void) {
    int64_t left = p_mul();
    while (tok == T_PLUS || tok == T_MINUS) {
        int op = tok; advance();
        int64_t right = p_mul();
        left = (op == T_PLUS) ? (int64_t)((uint64_t)left + (uint64_t)right)
                              : (int64_t)((uint64_t)left - (uint64_t)right);
    }
    return left;
}

static int64_t p_shift(void) {
    int64_t left = p_add();
    while (tok == T_SHL || tok == T_SHR) {
        int op = tok; advance();
        int64_t right = p_add();
        uint32_t v = (uint32_t)(left & 0xFFFFFFFF);
        int s = (int)(right & 31);
        left = (op == T_SHL) ? (int64_t)(v << s) : (int64_t)(v >> s);
    }
    return left;
}

static int64_t p_bitand(void) {
    int64_t left = p_shift();
    while (tok == T_AND) {
        advance(); int64_t right = p_shift();
        left = (int64_t)((uint32_t)(left & 0xFFFFFFFF) & (uint32_t)(right & 0xFFFFFFFF));
    }
    return left;
}

static int64_t p_bitxor(void) {
    int64_t left = p_bitand();
    while (tok == T_XOR) {
        advance(); int64_t right = p_bitand();
        left = (int64_t)((uint32_t)(left & 0xFFFFFFFF) ^ (uint32_t)(right & 0xFFFFFFFF));
    }
    return left;
}

static int64_t p_bitor(void) {
    int64_t left = p_bitxor();
    while (tok == T_OR) {
        advance(); int64_t right = p_bitxor();
        left = (int64_t)((uint32_t)(left & 0xFFFFFFFF) | (uint32_t)(right & 0xFFFFFFFF));
    }
    return left;
}

static int64_t p_hash(void) {
    int64_t left = p_bitor();
    while (tok == T_HASH) {
        advance(); int64_t right = p_bitor();
        uint32_t ua = (uint32_t)(left & 0xFFFFFFFF);
        uint32_t ub = (uint32_t)(right & 0xFFFFFFFF);
        left = (int64_t)((uint32_t)(ua * (uint32_t)0x9E3779B1U) ^ ub);
    }
    return left;
}

static int64_t expr(void) { return p_hash(); }

static void print_bin(int64_t v) {
    if (v == 0) { puts("0b0"); return; }
    uint64_t u;
    if (v < 0) { printf("-0b"); u = (uint64_t)(-(uint64_t)v); }
    else { printf("0b"); u = (uint64_t)v; }
    char buf[65]; int i = 0;
    while (u) { buf[i++] = '0' + (u & 1); u >>= 1; }
    for (int j = i - 1; j >= 0; j--) putchar(buf[j]);
    putchar('\n');
}

static void print_result(int64_t v, int hex, int bin) {
    if (hex) {
        if (v < 0) printf("-0x%" PRIx64 "\n", (uint64_t)(-(uint64_t)v));
        else printf("0x%" PRIx64 "\n", (uint64_t)v);
    } else if (bin) {
        print_bin(v);
    } else {
        printf("%" PRId64 "\n", v);
    }
}

int main(int argc, char **argv) {
    int hex = 0, bin = 0, file = 0;
    const char *arg = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-x")) hex = 1;
        else if (!strcmp(argv[i], "-b")) bin = 1;
        else if (!strcmp(argv[i], "-f")) file = 1;
        else arg = argv[i];
    }
    if (!arg) { fprintf(stderr, "Usage: evalx [-x|-b] [-f] <expr|file>\n"); return 1; }
    if (file) {
        FILE *f = fopen(arg, "r");
        if (!f) { fprintf(stderr, "Error: cannot open file\n"); return 1; }
        char line[4096];
        while (fgets(line, sizeof(line), f)) {
            int len = strlen(line);
            while (len > 0 && (line[len-1] == '\n' || line[len-1] == '\r')) line[--len] = 0;
            if (!len || line[0] == '#') continue;
            src = line; advance();
            if (tok == T_END) continue;
            int64_t v = expr();
            print_result(v, hex, bin);
        }
        fclose(f);
    } else {
        src = arg; advance();
        if (tok == T_END) return 0;
        int64_t v = expr();
        print_result(v, hex, bin);
    }
    return 0;
}
