/*
 * bundle_check.c - VLIW Bundle Structural Validator
 *
 * Reads a .vliw format file and validates:
 *   - Instruction syntax correctness
 *   - Slot assignment constraints (MUL only in B, LOAD/STORE only in M)
 *   - Physical register indices within [0, NUM_REGS)
 *   - No WAW conflicts within a bundle (two writes to same register)
 *
 * Usage: ./bundle_check <file.vliw> [--verbose]
 * Exit codes: 0 = valid, 1 = errors found, 2 = usage/file error
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define MAX_LINE 1024

static int op_in(const char *op, const char *list[]) {
    for (int i = 0; list[i]; i++)
        if (strcmp(op, list[i]) == 0)
            return 1;
    return 0;
}

static int parse_reg(const char *s) {
    if (!s || s[0] != 'r' || !isdigit((unsigned char)s[1]))
        return -1;
    return atoi(s + 1);
}

static const char *SLOT_A[] = {
    "ADD","SUB","AND","OR","XOR","SHL","SHR","MOV","MOVI", NULL};
static const char *SLOT_B[] = {
    "ADD","SUB","AND","OR","XOR","SHL","SHR","MOV","MOVI","MUL", NULL};
static const char *SLOT_M[] = {"LOAD","STORE", NULL};

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <file.vliw> [--verbose]\n", argv[0]);
        return 2;
    }

    int verbose = (argc > 2 && strcmp(argv[2], "--verbose") == 0);

    FILE *f = fopen(argv[1], "r");
    if (!f) {
        fprintf(stderr, "Error: cannot open '%s'\n", argv[1]);
        return 2;
    }

    char line[MAX_LINE];
    int num_regs = 24;
    int errors = 0;
    int n_bundles = 0;
    int in_bundle = 0;
    int bundle_dests[3];
    int n_dests = 0;

    while (fgets(line, sizeof(line), f)) {
        /* Strip trailing whitespace */
        int len = (int)strlen(line);
        while (len > 0 && isspace((unsigned char)line[len-1]))
            line[--len] = '\0';

        /* Skip to first non-space */
        char *p = line;
        while (isspace((unsigned char)*p)) p++;

        /* Skip blank lines and comments */
        if (*p == '\0' || *p == '#') continue;

        /* Header: NUM_REGS */
        if (strncmp(p, "NUM_REGS", 8) == 0) {
            num_regs = atoi(p + 9);
            if (verbose)
                printf("Header: NUM_REGS=%d\n", num_regs);
            continue;
        }
        /* Header: MEM_SIZE (not used for validation) */
        if (strncmp(p, "MEM_SIZE", 8) == 0) continue;

        /* BUNDLE header */
        if (strncmp(p, "BUNDLE", 6) == 0) {
            /* Check WAW for previous bundle */
            if (in_bundle) {
                for (int i = 0; i < n_dests; i++)
                    for (int j = i+1; j < n_dests; j++)
                        if (bundle_dests[i] > 0 &&
                            bundle_dests[i] == bundle_dests[j]) {
                            fprintf(stderr,
                                "ERROR: bundle %d: WAW on r%d\n",
                                n_bundles-1, bundle_dests[i]);
                            errors++;
                        }
            }
            n_bundles++;
            in_bundle = 1;
            n_dests = 0;
            memset(bundle_dests, -1, sizeof(bundle_dests));
            if (verbose)
                printf("Bundle %d\n", n_bundles-1);
            continue;
        }

        /* Slot line: "A: ...", "B: ...", "M: ..." */
        if (in_bundle &&
            (p[0] == 'A' || p[0] == 'B' || p[0] == 'M') &&
            p[1] == ':') {

            char slot_ch = p[0];
            const char **allowed = (slot_ch == 'A') ? SLOT_A :
                                   (slot_ch == 'B') ? SLOT_B : SLOT_M;
            const char *sname = (slot_ch == 'A') ? "A" :
                                (slot_ch == 'B') ? "B" : "M";

            /* Advance past "X: " */
            p += 2;
            while (isspace((unsigned char)*p)) p++;

            if (strcmp(p, "NOP") == 0) {
                if (verbose) printf("  %s: NOP\n", sname);
                continue;
            }

            /* Tokenize instruction */
            char tok[5][64];
            memset(tok, 0, sizeof(tok));
            int ntok = sscanf(p, "%63s %63s %63s %63s %63s",
                              tok[0], tok[1], tok[2], tok[3], tok[4]);
            if (ntok < 1) {
                fprintf(stderr, "ERROR: bundle %d slot %s: empty\n",
                        n_bundles-1, sname);
                errors++;
                continue;
            }

            char *op = tok[0];
            if (verbose) printf("  %s: %s\n", sname, p);

            /* Check slot constraint */
            if (!op_in(op, allowed)) {
                fprintf(stderr,
                    "ERROR: bundle %d: %s not allowed in slot %s\n",
                    n_bundles-1, op, sname);
                errors++;
            }

            /* Validate based on op type */
            if (strcmp(op,"ADD")==0 || strcmp(op,"SUB")==0 ||
                strcmp(op,"AND")==0 || strcmp(op,"OR")==0  ||
                strcmp(op,"XOR")==0 || strcmp(op,"SHL")==0 ||
                strcmp(op,"SHR")==0 || strcmp(op,"MUL")==0) {
                if (ntok != 4) {
                    fprintf(stderr,
                        "ERROR: bundle %d slot %s: %s needs 3 reg operands\n",
                        n_bundles-1, sname, op);
                    errors++;
                } else {
                    int rd = parse_reg(tok[1]);
                    int r1 = parse_reg(tok[2]);
                    int r2 = parse_reg(tok[3]);
                    if (rd < 0 || rd >= num_regs) {
                        fprintf(stderr,
                            "ERROR: bundle %d slot %s: dest %s out of range\n",
                            n_bundles-1, sname, tok[1]);
                        errors++;
                    }
                    if (r1 < 0 || r1 >= num_regs) {
                        fprintf(stderr,
                            "ERROR: bundle %d slot %s: src %s out of range\n",
                            n_bundles-1, sname, tok[2]);
                        errors++;
                    }
                    if (r2 < 0 || r2 >= num_regs) {
                        fprintf(stderr,
                            "ERROR: bundle %d slot %s: src %s out of range\n",
                            n_bundles-1, sname, tok[3]);
                        errors++;
                    }
                    if (rd >= 0 && n_dests < 3)
                        bundle_dests[n_dests++] = rd;
                }
            } else if (strcmp(op, "MOV") == 0) {
                if (ntok != 3) {
                    fprintf(stderr,
                        "ERROR: bundle %d slot %s: MOV needs 2 reg operands\n",
                        n_bundles-1, sname);
                    errors++;
                } else {
                    int rd = parse_reg(tok[1]);
                    int rs = parse_reg(tok[2]);
                    if (rd < 0 || rd >= num_regs) {
                        fprintf(stderr,
                            "ERROR: bundle %d slot %s: dest %s out of range\n",
                            n_bundles-1, sname, tok[1]);
                        errors++;
                    }
                    if (rs < 0 || rs >= num_regs) {
                        fprintf(stderr,
                            "ERROR: bundle %d slot %s: src %s out of range\n",
                            n_bundles-1, sname, tok[2]);
                        errors++;
                    }
                    if (rd >= 0 && n_dests < 3)
                        bundle_dests[n_dests++] = rd;
                }
            } else if (strcmp(op, "MOVI") == 0) {
                if (ntok != 3) {
                    fprintf(stderr,
                        "ERROR: bundle %d slot %s: MOVI needs reg + immediate\n",
                        n_bundles-1, sname);
                    errors++;
                } else {
                    int rd = parse_reg(tok[1]);
                    if (rd < 0 || rd >= num_regs) {
                        fprintf(stderr,
                            "ERROR: bundle %d slot %s: dest %s out of range\n",
                            n_bundles-1, sname, tok[1]);
                        errors++;
                    }
                    if (rd >= 0 && n_dests < 3)
                        bundle_dests[n_dests++] = rd;
                }
            } else if (strcmp(op, "LOAD") == 0) {
                if (ntok != 3) {
                    fprintf(stderr,
                        "ERROR: bundle %d slot %s: LOAD needs 2 reg operands\n",
                        n_bundles-1, sname);
                    errors++;
                } else {
                    int rd = parse_reg(tok[1]);
                    int ra = parse_reg(tok[2]);
                    if (rd < 0 || rd >= num_regs) {
                        fprintf(stderr,
                            "ERROR: bundle %d slot %s: dest %s out of range\n",
                            n_bundles-1, sname, tok[1]);
                        errors++;
                    }
                    if (ra < 0 || ra >= num_regs) {
                        fprintf(stderr,
                            "ERROR: bundle %d slot %s: addr %s out of range\n",
                            n_bundles-1, sname, tok[2]);
                        errors++;
                    }
                    if (rd >= 0 && n_dests < 3)
                        bundle_dests[n_dests++] = rd;
                }
            } else if (strcmp(op, "STORE") == 0) {
                if (ntok != 3) {
                    fprintf(stderr,
                        "ERROR: bundle %d slot %s: STORE needs 2 reg operands\n",
                        n_bundles-1, sname);
                    errors++;
                } else {
                    int ra = parse_reg(tok[1]);
                    int rv = parse_reg(tok[2]);
                    if (ra < 0 || ra >= num_regs) {
                        fprintf(stderr,
                            "ERROR: bundle %d slot %s: addr %s out of range\n",
                            n_bundles-1, sname, tok[1]);
                        errors++;
                    }
                    if (rv < 0 || rv >= num_regs) {
                        fprintf(stderr,
                            "ERROR: bundle %d slot %s: val %s out of range\n",
                            n_bundles-1, sname, tok[2]);
                        errors++;
                    }
                    /* STORE has no dest register */
                }
            } else {
                fprintf(stderr,
                    "ERROR: bundle %d slot %s: unknown op '%s'\n",
                    n_bundles-1, sname, op);
                errors++;
            }
        }
    }

    /* Check WAW for last bundle */
    if (in_bundle) {
        for (int i = 0; i < n_dests; i++)
            for (int j = i+1; j < n_dests; j++)
                if (bundle_dests[i] > 0 &&
                    bundle_dests[i] == bundle_dests[j]) {
                    fprintf(stderr,
                        "ERROR: bundle %d: WAW on r%d\n",
                        n_bundles-1, bundle_dests[i]);
                    errors++;
                }
    }

    fclose(f);

    if (errors > 0) {
        fprintf(stderr,
            "FAILED: %d error(s) in %d bundle(s)\n", errors, n_bundles);
        return 1;
    }

    printf("PASSED: %d bundle(s) validated (%d registers)\n",
           n_bundles, num_regs);
    return 0;
}
