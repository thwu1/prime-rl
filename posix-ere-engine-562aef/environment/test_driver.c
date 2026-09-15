#define _GNU_SOURCE
/* test_driver.c  –  Runs rxspencer-format test vectors against the regex engine.
 *
 *
 * Usage:  ./test_driver [test_vectors.txt]
 * Output: JSON   {"total":N,"passed":P,"failed":F,"details":[...]}
 */

#include "regex_engine.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define MAX_LINE 4096
#define MAX_SUB  16

/* ---- helpers ---- */

/* Map error name (minus REG_) to code.  Returns -1 if unknown. */
static int err_code(const char *name) {
    static const struct { const char *n; int c; } tbl[] = {
        {"NOMATCH",  REG_NOMATCH}, {"BADPAT",  REG_BADPAT},
        {"ECOLLATE", REG_ECOLLATE},{"ECTYPE",  REG_ECTYPE},
        {"EESCAPE",  REG_EESCAPE},{"ESUBREG", REG_ESUBREG},
        {"EBRACK",   REG_EBRACK}, {"EPAREN",  REG_EPAREN},
        {"EBRACE",   REG_EBRACE}, {"BADBR",   REG_BADBR},
        {"ERANGE",   REG_ERANGE}, {"ESPACE",  REG_ESPACE},
        {"BADRPT",   REG_BADRPT},
    };
    for (size_t i = 0; i < sizeof tbl / sizeof *tbl; i++)
        if (strcmp(name, tbl[i].n) == 0) return tbl[i].c;
    return -1;
}

/* Translate special characters: N→\n  S→' '  T→\t   (in-place). */
static void xlat(char *s) {
    char *r = s, *w = s;
    while (*r) {
        if (*r == 'N')      { *w++ = '\n'; r++; }
        else if (*r == 'S') { *w++ = ' ';  r++; }
        else if (*r == 'T') { *w++ = '\t'; r++; }
        else                { *w++ = *r++; }
    }
    *w = '\0';
}

/* Split line by tabs.  Returns field count.  Modifies buf. */
static int split_tabs(char *buf, char **fields, int maxf) {
    int n = 0;
    char *p = buf;
    while (n < maxf) {
        fields[n++] = p;
        p = strchr(p, '\t');
        if (!p) break;
        *p++ = '\0';
        /* skip extra tabs */
        while (*p == '\t') p++;
    }
    return n;
}

/* Build cflags / eflags from flag string (field 2).
   Returns 1 if this is a compile-error test (C flag). */
static int parse_flags(const char *f, int *cflags, int *eflags, int *is_comp_err) {
    *cflags = REG_EXTENDED;
    *eflags = 0;
    *is_comp_err = 0;
    for (const char *p = f; *p; p++) {
        switch (*p) {
        case '-': break;
        case 'C': *is_comp_err = 1; break;
        case 'i': *cflags |= REG_ICASE; break;
        case 'n': *cflags |= REG_NEWLINE; break;
        case 's': *cflags |= REG_NOSUB; break;
        case '^': *eflags |= REG_NOTBOL; break;
        case '$': *eflags |= REG_NOTEOL; break;
        case '&': break; /* test as both BRE/ERE — we only do ERE */
        case 'b': return 0; /* BRE-only: skip */
        case '#': return 0; /* STARTEND: skip */
        case 'p': return 0; /* PEND: skip */
        case 'm': return 0; /* NOSPEC: skip */
        }
    }
    return 1;
}

/* Compare a submatch against expected string (@ and - handling).
   'input' is the full input string (for positional checking).
   Returns 1 on match. */
static int cmp_match(const char *input, regmatch_t *pm, const char *exp) {
    if (strcmp(exp, "-") == 0) {
        /* non-participating subexpression: offsets should be -1 */
        return (pm->rm_so == -1 && pm->rm_eo == -1);
    }
    if (pm->rm_so == -1) return 0; /* got no match but expected one */

    if (exp[0] == '@') {
        /* zero-length match */
        if (pm->rm_so != pm->rm_eo) return 0;
        const char *after = exp + 1;
        int alen = (int)strlen(after);
        int remain = (int)strlen(input + pm->rm_eo);
        if (remain < alen) return 0;
        return (strncmp(input + pm->rm_eo, after, alen) == 0);
    }

    int mlen = pm->rm_eo - pm->rm_so;
    int elen = (int)strlen(exp);
    if (mlen != elen) return 0;
    return (strncmp(input + pm->rm_so, exp, elen) == 0);
}

/* JSON-escape a string into dst (which must be large enough). */
static void json_esc(char *dst, const char *src) {
    *dst++ = '"';
    for (; *src; src++) {
        if (*src == '"')       { *dst++ = '\\'; *dst++ = '"'; }
        else if (*src == '\\') { *dst++ = '\\'; *dst++ = '\\'; }
        else if (*src == '\n') { *dst++ = '\\'; *dst++ = 'n'; }
        else if (*src == '\t') { *dst++ = '\\'; *dst++ = 't'; }
        else if ((unsigned char)*src < 0x20) {
            dst += sprintf(dst, "\\u%04x", (unsigned char)*src);
        }
        else *dst++ = *src;
    }
    *dst++ = '"';
    *dst = '\0';
}

/* ---- main ---- */
int main(int argc, char **argv) {
    const char *path = (argc > 1) ? argv[1] : "test_vectors.txt";
    FILE *fp = fopen(path, "r");
    if (!fp) { fprintf(stderr, "Cannot open %s\n", path); return 1; }

    int total = 0, passed = 0, failed = 0;
    char line[MAX_LINE];
    int lineno = 0;

    /* collect detail strings */
    char **details = NULL;
    int  ndetails = 0, cap_details = 0;

    while (fgets(line, sizeof line, fp)) {
        lineno++;
        /* strip newline */
        char *nl = strchr(line, '\n');
        if (nl) *nl = '\0';

        /* skip comments and blanks */
        if (line[0] == '#' || line[0] == '\0') continue;

        char *fields[6];
        int nf = split_tabs(line, fields, 6);
        if (nf < 3) continue;

        /* parse flags */
        int cflags, eflags, is_comp_err;
        if (!parse_flags(fields[1], &cflags, &eflags, &is_comp_err))
            continue; /* skip unsupported test */

        /* pattern */
        char pattern[MAX_LINE];
        if (strcmp(fields[0], "\"\"") == 0)
            pattern[0] = '\0';
        else {
            strncpy(pattern, fields[0], sizeof pattern - 1);
            pattern[sizeof pattern - 1] = '\0';
        }

        total++;
        int ok = 0;
        char reason[MAX_LINE];
        reason[0] = '\0';

        if (is_comp_err) {
            /* field[2] is expected error name */
            int exp_err = err_code(fields[2]);
            regex_t re;
            int rc = regcomp(&re, pattern, cflags);
            if (rc == 0) {
                regfree(&re);
                snprintf(reason, sizeof reason,
                    "expected compile error %s but regcomp succeeded", fields[2]);
            } else if (exp_err >= 0 && rc != exp_err) {
                snprintf(reason, sizeof reason,
                    "expected error %s(%d) got %d", fields[2], exp_err, rc);
            } else {
                ok = 1;
            }
        } else {
            /* field[2] is input string */
            char input[MAX_LINE];
            if (strcmp(fields[2], "\"\"") == 0)
                input[0] = '\0';
            else {
                strncpy(input, fields[2], sizeof input - 1);
                input[sizeof input - 1] = '\0';
                xlat(input);
            }

            regex_t re;
            int rc = regcomp(&re, pattern, cflags);
            if (rc != 0) {
                snprintf(reason, sizeof reason,
                    "regcomp failed unexpectedly with code %d", rc);
            } else {
                regmatch_t pm[MAX_SUB];
                for (int k = 0; k < MAX_SUB; k++)
                    pm[k].rm_so = pm[k].rm_eo = -1;
                rc = regexec(&re, input, MAX_SUB, pm, eflags);

                int expect_match = (nf >= 4 && strlen(fields[3]) > 0);

                if (!expect_match) {
                    /* expect no match */
                    if (rc == 0) {
                        snprintf(reason, sizeof reason,
                            "expected no match but matched [%d,%d)",
                            pm[0].rm_so, pm[0].rm_eo);
                    } else {
                        ok = 1;
                    }
                } else {
                    /* expect match */
                    if (rc != 0) {
                        snprintf(reason, sizeof reason,
                            "expected match '%s' but regexec returned NOMATCH", fields[3]);
                    } else {
                        /* translate expected match */
                        char exp_match[MAX_LINE];
                        strncpy(exp_match, fields[3], sizeof exp_match - 1);
                        exp_match[sizeof exp_match - 1] = '\0';
                        xlat(exp_match);

                        if (!cmp_match(input, &pm[0], exp_match)) {
                            int mlen = pm[0].rm_eo - pm[0].rm_so;
                            char got[256];
                            if (mlen > 0 && mlen < 200)
                                snprintf(got, sizeof got, "%.*s", mlen, input + pm[0].rm_so);
                            else
                                snprintf(got, sizeof got, "[%d,%d)", pm[0].rm_so, pm[0].rm_eo);
                            snprintf(reason, sizeof reason,
                                "overall match: expected '%s' got '%s'", exp_match, got);
                        } else {
                            ok = 1;
                            /* check subexpressions if field 5 present */
                            if (nf >= 5 && strlen(fields[4]) > 0) {
                                char subs[MAX_LINE];
                                strncpy(subs, fields[4], sizeof subs - 1);
                                subs[sizeof subs - 1] = '\0';
                                xlat(subs);
                                /* split by comma */
                                int si = 1;
                                char *sp = subs, *tok;
                                while ((tok = strsep(&sp, ",")) != NULL && si < MAX_SUB) {
                                    if (!cmp_match(input, &pm[si], tok)) {
                                        ok = 0;
                                        snprintf(reason, sizeof reason,
                                            "submatch %d: expected '%s' got [%d,%d)",
                                            si, tok, pm[si].rm_so, pm[si].rm_eo);
                                        break;
                                    }
                                    si++;
                                }
                            }
                        }
                    }
                }
                regfree(&re);
            }
        }

        if (ok) {
            passed++;
        } else {
            failed++;
        }

        /* store detail */
        if (ndetails >= cap_details) {
            cap_details = cap_details ? cap_details * 2 : 64;
            details = realloc(details, cap_details * sizeof *details);
        }
        char det[MAX_LINE * 4];
        char jpat[MAX_LINE * 2], jreason[MAX_LINE * 2];
        json_esc(jpat, pattern);
        json_esc(jreason, reason);
        snprintf(det, sizeof det,
            "{\"line\":%d,\"pattern\":%s,\"result\":\"%s\",\"reason\":%s}",
            lineno, jpat, ok ? "PASS" : "FAIL", jreason);
        details[ndetails++] = strdup(det);
    }
    fclose(fp);

    /* Output JSON */
    printf("{\"total\":%d,\"passed\":%d,\"failed\":%d,\"details\":[\n", total, passed, failed);
    for (int i = 0; i < ndetails; i++) {
        printf("  %s%s\n", details[i], (i < ndetails - 1) ? "," : "");
        free(details[i]);
    }
    printf("]}\n");
    free(details);

    return (failed > 0) ? 1 : 0;
}
