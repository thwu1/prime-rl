/*
 * effects_oracle - Reference oracle for algebraic effect handler semantics.
 * Demonstrates correct output for various handler composition scenarios.
 *
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* ---- N-Queens solver (iterative backtracking) ---- */
static int qboard[20];

static int qsafe(int col) {
    for (int i = 0; i < col; i++) {
        if (qboard[i] == qboard[col] ||
            abs(qboard[i] - qboard[col]) == col - i)
            return 0;
    }
    return 1;
}

static void queens(int n) {
    int count = 0, first[20], first_set = 0, col = 0;
    for (int i = 0; i < n; i++) qboard[i] = 0;
    qboard[0] = 1;

    while (col >= 0) {
        if (qboard[col] > n) {
            qboard[col] = 0;
            col--;
            if (col >= 0) qboard[col]++;
            continue;
        }
        if (qsafe(col)) {
            if (col == n - 1) {
                count++;
                if (!first_set) {
                    for (int i = 0; i < n; i++) first[i] = qboard[i];
                    first_set = 1;
                }
                qboard[col]++;
            } else {
                col++;
                qboard[col] = 1;
            }
        } else {
            qboard[col]++;
        }
    }
    printf("count:%d\n", count);
    if (first_set) {
        printf("first:");
        for (int i = 0; i < n; i++) {
            if (i > 0) printf(",");
            printf("%d", first[i]);
        }
        printf("\n");
    }
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr,
            "effects_oracle - Reference implementation for algebraic effect handler semantics\n"
            "Usage: effects_oracle <scenario> [args...]\n"
            "       effects_oracle --list\n"
            "       effects_oracle --help\n");
        return 1;
    }

    if (strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "-h") == 0) {
        printf("effects_oracle - Algebraic effect handler semantics reference\n\n");
        printf("Usage: effects_oracle <scenario> [args...]\n\n");
        printf("Options:\n");
        printf("  --list    List available scenarios\n");
        printf("  --help    Show this help message\n\n");
        printf("Each scenario prints the expected output for a specific\n");
        printf("handler composition pattern. Use --list for scenario names,\n");
        printf("then run each scenario to discover its expected behavior.\n");
        return 0;
    }

    if (strcmp(argv[1], "--list") == 0) {
        printf("queens\nchoice-xor\nstate-choice\nchoice-state\ncompose-triple\n");
        return 0;
    }

    if (strcmp(argv[1], "queens") == 0) {
        if (argc < 3) {
            fprintf(stderr, "Usage: effects_oracle queens <N>  (1 <= N <= 12)\n");
            return 1;
        }
        int n = atoi(argv[2]);
        if (n < 1 || n > 12) {
            fprintf(stderr, "Error: N must be between 1 and 12\n");
            return 1;
        }
        queens(n);
        return 0;
    }

    /* choice-all(xor): resume(False) ++ resume(True) for each choice() */
    if (strcmp(argv[1], "choice-xor") == 0) {
        printf("False\nTrue\nTrue\nFalse\n");
        return 0;
    }

    /* pstate(0) { choice-all { surprising() } } — shared state */
    if (strcmp(argv[1], "state-choice") == 0) {
        printf("results:False,False,True,True,False\nstate:2\n");
        return 0;
    }

    /* choice-all { pstate(0) { surprising() } } — local state */
    if (strcmp(argv[1], "choice-state") == 0) {
        printf("(False,1)\n(False,1)\n");
        return 0;
    }

    /* Three-handler composition: reader + state + choice */
    if (strcmp(argv[1], "compose-triple") == 0) {
        if (argc < 3) {
            fprintf(stderr, "Usage: effects_oracle compose-triple <shared|local>\n");
            return 1;
        }
        if (strcmp(argv[2], "shared") == 0) {
            /* reader(10) { pstate(0) { choice-all { triple() } } } */
            printf("results:0,20\nstate:20\n");
        } else if (strcmp(argv[2], "local") == 0) {
            /* reader(10) { choice-all { pstate(0) { triple() } } } */
            printf("(0,10)\n(10,10)\n");
        } else {
            fprintf(stderr, "Unknown mode: '%s' (use 'shared' or 'local')\n", argv[2]);
            return 1;
        }
        return 0;
    }

    fprintf(stderr, "Unknown scenario: '%s'\nUse --list to see available scenarios.\n",
            argv[1]);
    return 1;
}
