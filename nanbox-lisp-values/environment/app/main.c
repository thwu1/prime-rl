#include "lisp.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *read_file(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc(len + 1);
    size_t rd = fread(buf, 1, len, f);
    buf[rd] = '\0';
    fclose(f);
    return buf;
}

int main(int argc, char **argv) {
    Env *env = default_env();

    /* --sizeof: print sizeof(Value) */
    if (argc == 2 && strcmp(argv[1], "--sizeof") == 0) {
        printf("%zu\n", sizeof(Value));
        return 0;
    }

    /* --eval "expr": evaluate expression string */
    if (argc >= 3 && strcmp(argv[1], "--eval") == 0) {
        Reader r = reader_new(argv[2]);
        Value result = val_nil();
        while (!reader_at_end(&r))
            result = eval(read_expr(&r), env);
        val_println(result, stdout);
        return 0;
    }

    /* file argument: evaluate file */
    if (argc >= 2) {
        char *code = read_file(argv[1]);
        if (!code) {
            fprintf(stderr, "Error: cannot open '%s'\n", argv[1]);
            return 1;
        }
        Reader r = reader_new(code);
        Value result = val_nil();
        while (!reader_at_end(&r))
            result = eval(read_expr(&r), env);
        val_println(result, stdout);
        free(code);
        return 0;
    }

    /* REPL */
    char line[4096];
    printf("lisp> ");
    fflush(stdout);
    while (fgets(line, sizeof(line), stdin)) {
        if (line[0] == '\n') { printf("lisp> "); fflush(stdout); continue; }
        Reader r = reader_new(line);
        Value result = val_nil();
        while (!reader_at_end(&r))
            result = eval(read_expr(&r), env);
        val_println(result, stdout);
        printf("lisp> ");
        fflush(stdout);
    }
    return 0;
}
