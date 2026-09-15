#include <stdio.h>
#include <stdlib.h>
#include "assembler.h"

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <assembly_file>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "r");
    if (!f) {
        perror(argv[1]);
        return 1;
    }

    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    rewind(f);

    char *src = malloc(len + 1);
    if (!src) { fclose(f); return 1; }
    if (fread(src, 1, len, f) != (size_t)len) {
        fclose(f); free(src); return 1;
    }
    src[len] = '\0';
    fclose(f);

    Program prog;
    if (parse_assembly(src, &prog) != 0) {
        free(src);
        return 1;
    }

    LayoutResult result;
    relax_layout(&prog, &result);
    print_json(&prog, &result);

    free(src);
    return 0;
}
