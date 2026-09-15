/* series_jit.c -- Fixed JIT series evaluator using libtcc (mob branch API)
 *
 *
 * Fixes applied vs. the broken original:
 *  1. tcc_relocate() takes a single argument in mob branch (no TCC_RELOCATE_AUTO)
 *  2. Use extern pow() declaration instead of #include <math.h> to avoid
 *     TCC include-path issues when running libtcc without full installation
 *  3. Add tcc_add_library_path + tcc_add_library("m") so pow() resolves
 *  4. Do NOT call tcc_delete() until after using the compiled function,
 *     because mob-branch tcc_relocate stores code inside TCCState memory
 *  5. Read series definitions from /app/input.json instead of hardcoding
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libtcc.h>

typedef double (*term_fn_t)(int);

#define MAX_SERIES 64
#define MAX_BODY 2048
#define MAX_NAME 128

typedef struct {
    char name[MAX_NAME];
    char term_body[MAX_BODY];
    int num_terms;
} Series;

static void err_func(void *opaque, const char *msg) {
    (void)opaque;
    fprintf(stderr, "TCC: %s\n", msg);
}

/* ---- Minimal JSON parser for our specific schema ---- */

/* Find the end of a JSON object, respecting string quoting */
static const char *find_obj_end(const char *start) {
    int depth = 0;
    int in_str = 0;
    for (const char *p = start; *p; p++) {
        if (in_str) {
            if (*p == '\\') { p++; continue; }
            if (*p == '"') in_str = 0;
        } else {
            if (*p == '"') in_str = 1;
            else if (*p == '{') depth++;
            else if (*p == '}') { depth--; if (depth == 0) return p; }
        }
    }
    return NULL;
}

/* Extract a JSON string value for a given key from an object substring */
static int json_get_str(const char *obj, const char *key, char *out, int maxlen) {
    char needle[256];
    snprintf(needle, sizeof needle, "\"%s\"", key);
    const char *p = strstr(obj, needle);
    if (!p) return -1;
    p += strlen(needle);
    while (*p && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r' || *p == ':')) p++;
    if (*p != '"') return -1;
    p++;
    int i = 0;
    while (*p && *p != '"' && i < maxlen - 1) {
        if (*p == '\\' && *(p + 1)) {
            p++;
            switch (*p) {
                case 'n':  out[i++] = '\n'; break;
                case 't':  out[i++] = '\t'; break;
                case '\\': out[i++] = '\\'; break;
                case '"':  out[i++] = '"';  break;
                default:   out[i++] = *p;   break;
            }
        } else {
            out[i++] = *p;
        }
        p++;
    }
    out[i] = '\0';
    return 0;
}

/* Extract a JSON integer value for a given key */
static int json_get_int(const char *obj, const char *key) {
    char needle[256];
    snprintf(needle, sizeof needle, "\"%s\"", key);
    const char *p = strstr(obj, needle);
    if (!p) return -1;
    p += strlen(needle);
    while (*p && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r' || *p == ':')) p++;
    return atoi(p);
}

static int parse_input(const char *path, Series *out, int max) {
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); return -1; }
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc(len + 1);
    if (!buf) { fclose(f); return -1; }
    fread(buf, 1, len, f);
    buf[len] = '\0';
    fclose(f);

    int count = 0;
    const char *p = strstr(buf, "\"series\"");
    if (!p) { free(buf); return -1; }
    p = strchr(p, '[');
    if (!p) { free(buf); return -1; }
    p++;

    while (count < max) {
        const char *obj_start = strchr(p, '{');
        if (!obj_start) break;
        const char *obj_end = find_obj_end(obj_start);
        if (!obj_end) break;

        int obj_len = (int)(obj_end - obj_start + 1);
        char *obj = malloc(obj_len + 1);
        memcpy(obj, obj_start, obj_len);
        obj[obj_len] = '\0';

        if (json_get_str(obj, "name", out[count].name, MAX_NAME) == 0 &&
            json_get_str(obj, "term_body", out[count].term_body, MAX_BODY) == 0) {
            out[count].num_terms = json_get_int(obj, "num_terms");
            if (out[count].num_terms > 0)
                count++;
        }

        free(obj);
        p = obj_end + 1;
    }

    free(buf);
    return count;
}

/* ---- Main ---- */

int main(void) {
    Series series[MAX_SERIES];
    int nseries = parse_input("/app/input.json", series, MAX_SERIES);
    if (nseries <= 0) {
        fprintf(stderr, "Failed to parse /app/input.json\n");
        return 1;
    }

    FILE *out = fopen("/app/output.txt", "w");
    if (!out) { perror("fopen /app/output.txt"); return 1; }

    for (int i = 0; i < nseries; i++) {
        TCCState *ts = tcc_new();
        if (!ts) {
            fprintf(stderr, "tcc_new failed for %s\n", series[i].name);
            fclose(out);
            return 1;
        }
        tcc_set_error_func(ts, NULL, err_func);
        tcc_set_output_type(ts, TCC_OUTPUT_MEMORY);

        /* Use extern declaration for pow() -- avoids needing TCC include
         * paths to find math.h and its transitive dependencies */
        char src[4096];
        snprintf(src, sizeof src,
            "extern double pow(double, double);\n"
            "double term_k(int k) {\n"
            "    %s\n"
            "}\n",
            series[i].term_body);

        if (tcc_compile_string(ts, src) < 0) {
            fprintf(stderr, "compile failed: %s\n", series[i].name);
            tcc_delete(ts);
            fclose(out);
            return 1;
        }

        /* Link libm so pow() resolves during relocation */
        tcc_add_library_path(ts, "/usr/lib/x86_64-linux-gnu");
        tcc_add_library(ts, "m");

        /* mob branch: tcc_relocate takes a single argument */
        if (tcc_relocate(ts) < 0) {
            fprintf(stderr, "relocate failed: %s\n", series[i].name);
            tcc_delete(ts);
            fclose(out);
            return 1;
        }

        term_fn_t fn = (term_fn_t)tcc_get_symbol(ts, "term_k");
        if (!fn) {
            fprintf(stderr, "symbol term_k not found: %s\n", series[i].name);
            tcc_delete(ts);
            fclose(out);
            return 1;
        }

        /* Compute the partial sum BEFORE tcc_delete -- mob branch stores
         * JIT code inside TCCState, so deleting invalidates fn */
        double sum = 0.0;
        for (int k = 0; k < series[i].num_terms; k++)
            sum += fn(k);

        fprintf(out, "%s %.17g\n", series[i].name, sum);

        tcc_delete(ts);
    }

    fclose(out);
    return 0;
}
