/* series_jit.c -- Evaluate mathematical series via libtcc JIT compilation.
 *
 * Dynamically compiles C function bodies and evaluates partial sums.
 * Uses TCC's libtcc for in-memory compilation.
 *
 * Build: gcc -O2 -o series_jit series_jit.c -I<tcc>/include -L<tcc>/lib -ltcc -ldl -lm
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libtcc.h>

typedef double (*term_fn_t)(int);

static void err_handler(void *opaque, const char *msg) {
    (void)opaque;
    fprintf(stderr, "TCC: %s\n", msg);
}

/* Compile a term function body string and return a callable pointer. */
static term_fn_t compile_term(const char *func_body) {
    TCCState *s = tcc_new();
    if (!s) return NULL;

    tcc_set_error_func(s, NULL, err_handler);
    tcc_set_output_type(s, TCC_OUTPUT_MEMORY);

    /* Wrap the function body in a complete C source with math.h
     * for pow() and other math functions. */
    char src[4096];
    snprintf(src, sizeof src,
        "#include <math.h>\n"
        "double term_k(int k) {\n"
        "    %s\n"
        "}\n", func_body);

    if (tcc_compile_string(s, src) < 0) {
        tcc_delete(s);
        return NULL;
    }

    /* Use TCC_RELOCATE_AUTO so TCC manages memory allocation for the
     * generated code.  The code buffer is separate from the TCCState
     * and survives tcc_delete(). */
    if (tcc_relocate(s, TCC_RELOCATE_AUTO) < 0) {
        tcc_delete(s);
        return NULL;
    }

    term_fn_t fn = (term_fn_t)tcc_get_symbol(s, "term_k");

    /* Safe to delete -- TCC_RELOCATE_AUTO ensures code lives independently */
    tcc_delete(s);

    return fn;
}

int main(void) {
    /* Standard benchmark series */
    struct { const char *name; const char *body; int n; } series[] = {
        {"leibniz_pi4",
         "return (k % 2 == 0 ? 1.0 : -1.0) / (2.0 * k + 1.0);",
         10000000},
        {"basel_pi2_6",
         "return 1.0 / (((double)k+1.0) * ((double)k+1.0));",
         10000000},
        {"euler_e",
         "double f = 1.0; for(int i = 1; i <= k; i++) f *= i; return 1.0 / f;",
         25},
        {"machin_pi4",
         "double x1=1.0/5.0, x2=1.0/239.0; "
         "double t1=(k%2==0?1.0:-1.0)*pow(x1,2*k+1)/(2*k+1); "
         "double t2=(k%2==0?1.0:-1.0)*pow(x2,2*k+1)/(2*k+1); "
         "return 4.0*t1-t2;",
         30},
        {"catalan_G",
         "return (k % 2 == 0 ? 1.0 : -1.0) / ((2.0*k+1.0) * (2.0*k+1.0));",
         1000000}
    };
    int nseries = sizeof(series) / sizeof(series[0]);

    FILE *out = fopen("/app/output.txt", "w");
    if (!out) { perror("fopen"); return 1; }

    for (int i = 0; i < nseries; i++) {
        term_fn_t fn = compile_term(series[i].body);
        if (!fn) {
            fprintf(stderr, "Failed to compile: %s\n", series[i].name);
            fclose(out);
            return 1;
        }
        double sum = 0.0;
        for (int k = 0; k < series[i].n; k++)
            sum += fn(k);
        fprintf(out, "%s %.17g\n", series[i].name, sum);
    }

    fclose(out);
    return 0;
}
