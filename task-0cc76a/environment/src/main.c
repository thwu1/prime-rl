#include "parser.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <image_file>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror("fopen");
        return 1;
    }

    fseek(f, 0, SEEK_END);
    long file_len = ftell(f);
    if (file_len <= 0) {
        fclose(f);
        fprintf(stderr, "Empty or invalid file\n");
        return 1;
    }
    size_t len = (size_t)file_len;
    fseek(f, 0, SEEK_SET);

    uint8_t *data = (uint8_t *)malloc(len);
    if (!data) {
        fclose(f);
        return 1;
    }
    size_t nread = fread(data, 1, len, f);
    fclose(f);

    if (nread != len) {
        free(data);
        fprintf(stderr, "Failed to read file\n");
        return 1;
    }

    image_t *img = img_parse(data, len);
    if (img) {
        printf("Parsed image: %ux%u, %u channels\n",
               img->width, img->height, img->channels);
        if (img->palette)
            printf("Palette: %u colors\n", img->palette_count);
        if (img->comment)
            printf("Comment: %s\n", img->comment);
        if (img->offsets)
            printf("Offsets: %u entries\n", img->offset_count);
        img_free(img);
    } else {
        printf("Parse failed\n");
    }

    free(data);
    return 0;
}
