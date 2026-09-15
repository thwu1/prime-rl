#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

/* ===== Dynamic Buffer ===== */
typedef struct { char *d; size_t n, c; } Buf;

static void buf_init(Buf *b) {
    b->c = 256; b->n = 0;
    b->d = (char *)malloc(b->c);
}
static void buf_free(Buf *b) { free(b->d); }

static void buf_putc(Buf *b, char ch) {
    if (b->n + 2 >= b->c) { b->c *= 2; b->d = (char *)realloc(b->d, b->c); }
    b->d[b->n++] = ch;
}
static void buf_puts(Buf *b, const char *s) {
    while (*s) buf_putc(b, *s++);
}
static void buf_putn(Buf *b, const char *s, size_t n) {
    for (size_t i = 0; i < n; i++) buf_putc(b, s[i]);
}
static char *buf_cstr(Buf *b) {
    if (b->n >= b->c) { b->c = b->c * 2 + 1; b->d = (char *)realloc(b->d, b->c); }
    b->d[b->n] = '\0';
    return b->d;
}

/* ===== Variables ===== */
#define MAX_VARS 256
#define MAX_KEY 128
#define MAX_VAL 4096
typedef struct { char k[MAX_KEY]; char v[MAX_VAL]; } Var;
static Var g_vars[MAX_VARS];
static int g_nvars = 0;

static void var_set(const char *k, const char *v) {
    for (int i = 0; i < g_nvars; i++) {
        if (strcmp(g_vars[i].k, k) == 0) {
            strncpy(g_vars[i].v, v, MAX_VAL - 1);
            g_vars[i].v[MAX_VAL - 1] = '\0';
            return;
        }
    }
    if (g_nvars < MAX_VARS) {
        strncpy(g_vars[g_nvars].k, k, MAX_KEY - 1);
        g_vars[g_nvars].k[MAX_KEY - 1] = '\0';
        strncpy(g_vars[g_nvars].v, v, MAX_VAL - 1);
        g_vars[g_nvars].v[MAX_VAL - 1] = '\0';
        g_nvars++;
    }
}
static const char *var_get(const char *k) {
    for (int i = 0; i < g_nvars; i++)
        if (strcmp(g_vars[i].k, k) == 0) return g_vars[i].v;
    return NULL;
}
static int var_exists(const char *k) { return var_get(k) != NULL; }

/* ===== Globals ===== */
static int g_had_error = 0;

/* ===== Forward Declarations ===== */
static void process(const char *in, size_t len, Buf *out);

/* ===== Brace Matching ===== */
static int find_close_brace(const char *in, size_t len, size_t start) {
    int depth = 0;
    for (size_t i = start; i < len; i++) {
        if (in[i] == '{') depth++;
        else if (in[i] == '}') { depth--; if (depth == 0) return (int)i; }
    }
    return -1;
}

/* ===== Argument Splitting on | at brace depth 0 ===== */
static char **split_args(const char *body, size_t blen, int *count) {
    int cap = 8;
    char **args = (char **)malloc(cap * sizeof(char *));
    *count = 0;
    int depth = 0;
    size_t start = 0;
    for (size_t i = 0; i <= blen; i++) {
        if (i < blen && body[i] == '{') depth++;
        else if (i < blen && body[i] == '}') depth--;
        else if (i == blen || (body[i] == '|' && depth == 0)) {
            if (*count >= cap) { cap *= 2; args = (char **)realloc(args, cap * sizeof(char *)); }
            size_t alen = i - start;
            args[*count] = (char *)malloc(alen + 1);
            memcpy(args[*count], body + start, alen);
            args[*count][alen] = '\0';
            (*count)++;
            start = i + 1;
        }
    }
    return args;
}
static void free_args(char **args, int count) {
    for (int i = 0; i < count; i++) free(args[i]);
    free(args);
}

/* ===== Directive Handler ===== */
static void handle_directive(const char *name, size_t nlen,
                             const char *body, size_t blen, Buf *out) {
    char nm[64];
    size_t nn = nlen < 63 ? nlen : 63;
    memcpy(nm, name, nn); nm[nn] = '\0';

    /* Simple wrapping tags: b, i, u, s, code */
    {
        const char *stags[] = {"b","i","u","s","code",NULL};
        for (int t = 0; stags[t]; t++) {
            if (strcmp(nm, stags[t]) == 0) {
                Buf pb; buf_init(&pb);
                process(body, blen, &pb);
                buf_putc(out, '<'); buf_puts(out, stags[t]); buf_putc(out, '>');
                buf_puts(out, buf_cstr(&pb));
                buf_puts(out, "</"); buf_puts(out, stags[t]); buf_putc(out, '>');
                buf_free(&pb);
                return;
            }
        }
    }

    /* Headings h1-h6 */
    if (nm[0] == 'h' && nn == 2 && isdigit((unsigned char)nm[1])) {
        if (nm[1] >= '1' && nm[1] <= '6') {
            Buf pb; buf_init(&pb);
            process(body, blen, &pb);
            buf_putc(out, '<'); buf_putn(out, nm, 2); buf_putc(out, '>');
            buf_puts(out, buf_cstr(&pb));
            buf_puts(out, "</"); buf_putn(out, nm, 2); buf_putc(out, '>');
            buf_free(&pb);
        } else {
            buf_puts(out, "[ERR:HEAD]");
            g_had_error = 1;
        }
        return;
    }

    /* link{url|text} — only first | splits url from text */
    if (strcmp(nm, "link") == 0) {
        int argc; char **args = split_args(body, blen, &argc);
        if (argc >= 1) {
            Buf pu; buf_init(&pu);
            process(args[0], strlen(args[0]), &pu);
            char *url = buf_cstr(&pu);
            buf_puts(out, "<a href=\"");
            buf_puts(out, url);
            buf_puts(out, "\">");
            if (argc >= 2) {
                Buf raw; buf_init(&raw);
                for (int i = 1; i < argc; i++) {
                    if (i > 1) buf_putc(&raw, '|');
                    buf_puts(&raw, args[i]);
                }
                Buf pt; buf_init(&pt);
                process(raw.d, raw.n, &pt);
                buf_puts(out, buf_cstr(&pt));
                buf_free(&raw); buf_free(&pt);
            } else {
                buf_puts(out, url);
            }
            buf_puts(out, "</a>");
            buf_free(&pu);
        }
        free_args(args, argc);
        return;
    }

    /* img{url|alt} */
    if (strcmp(nm, "img") == 0) {
        int argc; char **args = split_args(body, blen, &argc);
        if (argc >= 1) {
            Buf pu; buf_init(&pu);
            process(args[0], strlen(args[0]), &pu);
            buf_puts(out, "<img src=\"");
            buf_puts(out, buf_cstr(&pu));
            buf_puts(out, "\" alt=\"");
            if (argc >= 2) {
                Buf pa; buf_init(&pa);
                process(args[1], strlen(args[1]), &pa);
                buf_puts(out, buf_cstr(&pa));
                buf_free(&pa);
            }
            buf_puts(out, "\"/>");
            buf_free(&pu);
        }
        free_args(args, argc);
        return;
    }

    /* color{color|text} */
    if (strcmp(nm, "color") == 0) {
        int argc; char **args = split_args(body, blen, &argc);
        if (argc >= 2) {
            Buf pc; buf_init(&pc); Buf pt; buf_init(&pt);
            process(args[0], strlen(args[0]), &pc);
            process(args[1], strlen(args[1]), &pt);
            buf_puts(out, "<span style=\"color:");
            buf_puts(out, buf_cstr(&pc));
            buf_puts(out, "\">");
            buf_puts(out, buf_cstr(&pt));
            buf_puts(out, "</span>");
            buf_free(&pc); buf_free(&pt);
        }
        free_args(args, argc);
        return;
    }

    /* upper{text} */
    if (strcmp(nm, "upper") == 0) {
        Buf pb; buf_init(&pb);
        process(body, blen, &pb);
        char *s = buf_cstr(&pb);
        for (size_t i = 0; s[i]; i++)
            buf_putc(out, (char)toupper((unsigned char)s[i]));
        buf_free(&pb);
        return;
    }

    /* lower{text} */
    if (strcmp(nm, "lower") == 0) {
        Buf pb; buf_init(&pb);
        process(body, blen, &pb);
        char *s = buf_cstr(&pb);
        for (size_t i = 0; s[i]; i++)
            buf_putc(out, (char)tolower((unsigned char)s[i]));
        buf_free(&pb);
        return;
    }

    /* rev{text} */
    if (strcmp(nm, "rev") == 0) {
        Buf pb; buf_init(&pb);
        process(body, blen, &pb);
        char *s = buf_cstr(&pb);
        size_t slen = strlen(s);
        for (size_t i = slen; i > 0; i--)
            buf_putc(out, s[i - 1]);
        buf_free(&pb);
        return;
    }

    /* len{text} */
    if (strcmp(nm, "len") == 0) {
        Buf pb; buf_init(&pb);
        process(body, blen, &pb);
        char *s = buf_cstr(&pb);
        char num[32];
        snprintf(num, sizeof(num), "%zu", strlen(s));
        buf_puts(out, num);
        buf_free(&pb);
        return;
    }

    /* rep{n|text} */
    if (strcmp(nm, "rep") == 0) {
        int argc; char **args = split_args(body, blen, &argc);
        if (argc >= 2) {
            Buf pn; buf_init(&pn);
            process(args[0], strlen(args[0]), &pn);
            int n = atoi(buf_cstr(&pn));
            buf_free(&pn);
            if (n < 0 || n > 99) {
                buf_puts(out, "[ERR:REP]");
                g_had_error = 1;
            } else {
                Buf pt; buf_init(&pt);
                process(args[1], strlen(args[1]), &pt);
                char *text = buf_cstr(&pt);
                for (int r = 0; r < n; r++) buf_puts(out, text);
                buf_free(&pt);
            }
        }
        free_args(args, argc);
        return;
    }

    /* esc{text} — HTML escape */
    if (strcmp(nm, "esc") == 0) {
        Buf pb; buf_init(&pb);
        process(body, blen, &pb);
        char *s = buf_cstr(&pb);
        for (size_t i = 0; s[i]; i++) {
            switch (s[i]) {
            case '&': buf_puts(out, "&amp;"); break;
            case '<': buf_puts(out, "&lt;"); break;
            case '>': buf_puts(out, "&gt;"); break;
            case '"': buf_puts(out, "&quot;"); break;
            default:  buf_putc(out, s[i]); break;
            }
        }
        buf_free(&pb);
        return;
    }

    /* set{key=value} — key is literal, value is processed */
    if (strcmp(nm, "set") == 0) {
        int depth = 0;
        int eq_pos = -1;
        for (size_t j = 0; j < blen; j++) {
            if (body[j] == '{') depth++;
            else if (body[j] == '}') depth--;
            else if (body[j] == '=' && depth == 0) { eq_pos = (int)j; break; }
        }
        if (eq_pos >= 0) {
            char key[MAX_KEY];
            size_t klen = (size_t)eq_pos < MAX_KEY - 1 ? (size_t)eq_pos : MAX_KEY - 1;
            memcpy(key, body, klen); key[klen] = '\0';
            Buf pv; buf_init(&pv);
            process(body + eq_pos + 1, blen - (size_t)eq_pos - 1, &pv);
            var_set(key, buf_cstr(&pv));
            buf_free(&pv);
        }
        return; /* no output */
    }

    /* get{key} — key is literal, not processed */
    if (strcmp(nm, "get") == 0) {
        char key[MAX_KEY];
        size_t klen = blen < MAX_KEY - 1 ? blen : MAX_KEY - 1;
        memcpy(key, body, klen); key[klen] = '\0';
        const char *val = var_get(key);
        if (val) buf_puts(out, val);
        else {
            buf_puts(out, "[UNDEF:");
            buf_puts(out, key);
            buf_puts(out, "]");
        }
        return;
    }

    /* if{key|content} — key is literal, content processed only if true */
    if (strcmp(nm, "if") == 0) {
        int argc; char **args = split_args(body, blen, &argc);
        if (argc >= 2 && var_exists(args[0])) {
            process(args[1], strlen(args[1]), out);
        }
        free_args(args, argc);
        return;
    }

    /* unless{key|content} — key is literal, content processed only if false */
    if (strcmp(nm, "unless") == 0) {
        int argc; char **args = split_args(body, blen, &argc);
        if (argc >= 2 && !var_exists(args[0])) {
            process(args[1], strlen(args[1]), out);
        }
        free_args(args, argc);
        return;
    }

    /* list{a|b|c} */
    if (strcmp(nm, "list") == 0) {
        int argc; char **args = split_args(body, blen, &argc);
        buf_puts(out, "<ul>");
        for (int i = 0; i < argc; i++) {
            Buf pi; buf_init(&pi);
            process(args[i], strlen(args[i]), &pi);
            buf_puts(out, "<li>"); buf_puts(out, buf_cstr(&pi)); buf_puts(out, "</li>");
            buf_free(&pi);
        }
        buf_puts(out, "</ul>");
        free_args(args, argc);
        return;
    }

    /* olist{a|b|c} */
    if (strcmp(nm, "olist") == 0) {
        int argc; char **args = split_args(body, blen, &argc);
        buf_puts(out, "<ol>");
        for (int i = 0; i < argc; i++) {
            Buf pi; buf_init(&pi);
            process(args[i], strlen(args[i]), &pi);
            buf_puts(out, "<li>"); buf_puts(out, buf_cstr(&pi)); buf_puts(out, "</li>");
            buf_free(&pi);
        }
        buf_puts(out, "</ol>");
        free_args(args, argc);
        return;
    }

    /* Unknown directive */
    buf_puts(out, "[ERR:UNK:");
    buf_puts(out, nm);
    buf_puts(out, "]");
    g_had_error = 1;
}

/* ===== Main Processing ===== */
static void process(const char *in, size_t len, Buf *out) {
    size_t i = 0;
    while (i < len) {
        if (in[i] == '@') {
            /* @@ escape */
            if (i + 1 < len && in[i + 1] == '@') {
                buf_putc(out, '@');
                i += 2;
                continue;
            }
            /* Directive */
            if (i + 1 < len && isalpha((unsigned char)in[i + 1])) {
                size_t ns = i + 1, j = ns;
                while (j < len && (isalnum((unsigned char)in[j]) || in[j] == '_'))
                    j++;
                size_t nlen = j - ns;
                char nm[64];
                size_t nn = nlen < 63 ? nlen : 63;
                memcpy(nm, in + ns, nn); nm[nn] = '\0';

                /* Standalone: hr, br — always standalone */
                if (strcmp(nm, "hr") == 0) {
                    buf_puts(out, "<hr/>");
                    i = j; continue;
                }
                if (strcmp(nm, "br") == 0) {
                    buf_puts(out, "<br/>");
                    i = j; continue;
                }

                /* Expect { */
                if (j < len && in[j] == '{') {
                    int close = find_close_brace(in, len, j);
                    if (close < 0) {
                        buf_puts(out, "[ERR:UNCLOSED:");
                        buf_putn(out, in + ns, nlen);
                        buf_puts(out, "]");
                        g_had_error = 1;
                        i = len;
                        continue;
                    }
                    handle_directive(in + ns, nlen,
                                     in + j + 1, (size_t)(close - (int)j - 1), out);
                    i = (size_t)close + 1;
                    continue;
                }

                /* No { — output @name literally */
                buf_putc(out, '@');
                buf_putn(out, in + ns, nlen);
                i = j;
                continue;
            }
            /* @ followed by non-alpha, non-@ */
            buf_putc(out, '@');
            i++;
        } else {
            buf_putc(out, in[i]);
            i++;
        }
    }
}

/* ===== Main ===== */
int main(int argc, char *argv[]) {
    const char *filename = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--help") == 0) {
            printf("Usage: textfmt [OPTIONS] [FILE]\n"
                   "Transform text using custom markup rules.\n"
                   "  --help     Show this message\n"
                   "  --version  Show version\n"
                   "\nReads from stdin if no file given. Writes to stdout.\n"
                   "Processes custom @-directives in the input text.\n");
            return 0;
        }
        if (strcmp(argv[i], "--version") == 0) {
            printf("textfmt 1.0.0\n");
            return 0;
        }
        filename = argv[i];
    }

    FILE *fp;
    if (filename) {
        fp = fopen(filename, "r");
        if (!fp) { fprintf(stderr, "Error: cannot open '%s'\n", filename); return 1; }
    } else {
        fp = stdin;
    }

    Buf input; buf_init(&input);
    int ch;
    while ((ch = fgetc(fp)) != EOF) buf_putc(&input, (char)ch);
    if (filename) fclose(fp);

    Buf output; buf_init(&output);
    process(input.d, input.n, &output);

    fwrite(output.d, 1, output.n, stdout);

    buf_free(&input);
    buf_free(&output);
    return g_had_error ? 1 : 0;
}
