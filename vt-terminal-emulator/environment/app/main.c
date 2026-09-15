
#include "terminal.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    int width = 80, height = 24;
    int chunk_size = 0;

    if (argc >= 3) {
        width = atoi(argv[1]);
        height = atoi(argv[2]);
    }
    if (argc >= 4) {
        chunk_size = atoi(argv[3]);
    }

    Terminal *term = terminal_create(width, height);
    if (!term) {
        fprintf(stderr, "Failed to create terminal\n");
        return 1;
    }

    /* Read all of stdin into a buffer */
    uint8_t *buf = NULL;
    size_t buf_size = 0, buf_cap = 4096;
    buf = (uint8_t *)malloc(buf_cap);

    for (;;) {
        if (buf_size >= buf_cap) {
            buf_cap *= 2;
            buf = (uint8_t *)realloc(buf, buf_cap);
        }
        size_t n = fread(buf + buf_size, 1, buf_cap - buf_size, stdin);
        if (n == 0) break;
        buf_size += n;
    }

    /* Feed input to the terminal, optionally in fixed-size chunks */
    if (chunk_size > 0) {
        for (size_t i = 0; i < buf_size; ) {
            size_t n = (size_t)chunk_size;
            if (i + n > buf_size) n = buf_size - i;
            terminal_process(term, buf + i, n);
            i += n;
        }
    } else {
        terminal_process(term, buf, buf_size);
    }

    /* Emit terminal state as JSON to stdout */
    printf("{\"cursor\":{\"x\":%d,\"y\":%d},\"width\":%d,\"height\":%d,\"cells\":[",
           terminal_get_cursor_x(term), terminal_get_cursor_y(term), width, height);

    for (int y = 0; y < height; y++) {
        if (y > 0) putchar(',');
        putchar('[');
        for (int x = 0; x < width; x++) {
            if (x > 0) putchar(',');
            Cell c = terminal_get_cell(term, x, y);
            printf("{\"cp\":%u,\"fg\":[%u,%u,%u],\"bg\":[%u,%u,%u],\"at\":%u}",
                   c.codepoint,
                   c.fg_r, c.fg_g, c.fg_b,
                   c.bg_r, c.bg_g, c.bg_b,
                   c.attrs);
        }
        putchar(']');
    }
    printf("]}\n");

    terminal_destroy(term);
    free(buf);
    return 0;
}
