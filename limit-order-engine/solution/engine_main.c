/*
 * Limit Order Book Matching Engine — CLI Driver
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "engine_api.h"

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <input.bin> <output.txt>\n", argv[0]);
        return 1;
    }

    FILE *fp = fopen(argv[1], "rb");
    if (!fp) { perror("open input"); return 1; }
    fseek(fp, 0, SEEK_END);
    long fsz = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    uint8_t *data = (uint8_t *)malloc((size_t)fsz);
    if (!data) { perror("malloc"); return 1; }
    if ((long)fread(data, 1, (size_t)fsz, fp) != fsz) {
        perror("fread"); return 1;
    }
    fclose(fp);

    lob_book *book = lob_book_create();
    if (!book) { fprintf(stderr, "Failed to create book\n"); return 1; }

    int rc = lob_process_feed(book, data, (size_t)fsz, argv[2]);

    lob_book_destroy(book);
    free(data);
    return rc;
}
