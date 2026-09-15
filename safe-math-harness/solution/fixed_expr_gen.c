/*
 * expr_gen.c - Deterministic random arithmetic expression generator
 *
 * Generates a C program that evaluates random arithmetic expressions
 * over int32_t global variables using safe math wrappers, then prints
 * a CRC32 checksum of all variable values. The generated program must
 * be free of undefined behavior if safe_math.h is correct.
 *
 * Usage: ./expr_gen <seed> > test_program.c
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <limits.h>

#define NUM_VARS   10
#define NUM_STMTS  150

/* Values chosen to exercise common UB edge cases */
static const int32_t interesting_values[] = {
    0, 1, -1, 2, -2,
    INT32_MAX, INT32_MIN, INT32_MAX - 1, INT32_MIN + 1,
    31, 32, -31, 42, 100, -100,
    0x7F, 0xFF, 0x7FFF, 0xFFFF
};
#define NUM_INTERESTING ((int)(sizeof(interesting_values)/sizeof(interesting_values[0])))

/* Knuth LCG */
static uint32_t prng_state;

static uint32_t prng_next(void) {
    prng_state = prng_state * 1664525u + 1013904223u;
    return prng_state;
}

static uint32_t prng_range(uint32_t n) {
    if (n == 0) return 0;
    return prng_next() % n;
}

static int32_t random_value(void) {
    /* 30% chance of an interesting constant */
    if (prng_range(10) < 3) {
        return interesting_values[prng_range(NUM_INTERESTING)];
    }
    /* Otherwise generate a random int32_t in a safe range */
    int32_t r = (int32_t)(prng_next() % (uint32_t)INT32_MAX);
    if (prng_range(2)) r = -r;
    return r;
}

static void print_int32_literal(int32_t val) {
    if (val == INT32_MIN) {
        printf("(-2147483647 - 1)");
    } else {
        printf("%d", (int)val);
    }
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <seed>\n", argv[0]);
        return 1;
    }

    prng_state = (uint32_t)atoi(argv[1]);

    /* --- Emit includes --- */
    printf("#include <stdio.h>\n");
    printf("#include <stdint.h>\n");
    printf("#include <limits.h>\n");
    printf("#include \"safe_math.h\"\n");
    printf("#include \"crc32.h\"\n\n");

    /* --- Emit global variables --- */
    for (int i = 0; i < NUM_VARS; i++) {
        int32_t val = random_value();
        printf("static int32_t g_%d = ", i);
        print_int32_literal(val);
        printf(";\n");
    }
    printf("\n");

    /* --- Emit compute() --- */
    printf("static void compute(void) {\n");

    static const char *bin_ops[] = {
        "safe_add_int32_t",
        "safe_sub_int32_t",
        "safe_mul_int32_t",
        "safe_div_int32_t",
        "safe_mod_int32_t",
        "safe_lshift_int32_t",
        "safe_rshift_int32_t"
    };
    int num_bin_ops = 7;

    for (int i = 0; i < NUM_STMTS; i++) {
        int dest = prng_range(NUM_VARS);
        int op_type = prng_range(num_bin_ops + 2);

        if (op_type == num_bin_ops) {
            /* Unary negation */
            int src = prng_range(NUM_VARS);
            printf("    g_%d = safe_neg_int32_t(g_%d);\n", dest, src);
        } else if (op_type == num_bin_ops + 1) {
            /* Inject an interesting constant */
            int32_t val = interesting_values[prng_range(NUM_INTERESTING)];
            printf("    g_%d = ", dest);
            print_int32_literal(val);
            printf(";\n");
        } else {
            /* Binary operation */
            int src1 = prng_range(NUM_VARS);
            int src2 = prng_range(NUM_VARS);
            printf("    g_%d = %s(g_%d, g_%d);\n",
                   dest, bin_ops[op_type], src1, src2);
        }
    }

    printf("}\n\n");

    /* --- Emit main() --- */
    printf("int main(void) {\n");
    printf("    crc32_init();\n");
    printf("    compute();\n");
    for (int i = 0; i < NUM_VARS; i++) {
        printf("    transparent_crc((uint64_t)(uint32_t)g_%d, \"g_%d\", 0);\n", i, i);
    }
    printf("    printf(\"checksum = %%08x\\n\", (unsigned)crc32_finalize());\n");
    printf("    return 0;\n");
    printf("}\n");

    return 0;
}
