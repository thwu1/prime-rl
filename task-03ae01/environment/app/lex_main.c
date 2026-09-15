/*
 * Main driver for the Cool Flex lexer.
 * Sets up yyin from a file argument and calls yylex(), which scans
 * the input and prints JSON token lines to stdout.
 *
 */
#include <stdio.h>
#include <stdlib.h>

extern FILE *yyin;
extern int yylex(void);

int yywrap(void) { return 1; }

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <file.cl>\n", argv[0]);
        return 1;
    }
    yyin = fopen(argv[1], "r");
    if (!yyin) {
        perror(argv[1]);
        return 1;
    }
    yylex();
    fclose(yyin);
    return 0;
}
