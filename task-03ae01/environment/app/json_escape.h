/*
 * JSON string escaping utility for the Cool lexer's token output.
 *
 */
#ifndef JSON_ESCAPE_H
#define JSON_ESCAPE_H

#include <stdio.h>

/*
 * Print a string as a JSON-escaped value with surrounding double quotes.
 * Handles: \", \\, \n, \t, \b, \f, \r, and \uXXXX for control characters.
 */
static void json_print_escaped(FILE *out, const char *s, int len) {
    fputc('"', out);
    for (int i = 0; i < len; i++) {
        unsigned char c = (unsigned char)s[i];
        switch (c) {
            case '"':  fputs("\\\"", out); break;
            case '\\': fputs("\\\\", out); break;
            case '\n': fputs("\\n", out);  break;
            case '\t': fputs("\\t", out);  break;
            case '\b': fputs("\\b", out);  break;
            case '\f': fputs("\\f", out);  break;
            case '\r': fputs("\\r", out);  break;
            default:
                if (c < 0x20) {
                    fprintf(out, "\\u%04x", c);
                } else {
                    fputc(c, out);
                }
                break;
        }
    }
    fputc('"', out);
}

#endif /* JSON_ESCAPE_H */
