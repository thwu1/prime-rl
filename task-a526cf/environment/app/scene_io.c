#include "scene_io.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

scene_t *scene_parse(const char *filename) {
    FILE *f = fopen(filename, "r");
    if (!f) return NULL;

    scene_t *scene = calloc(1, sizeof(scene_t));
    if (!scene) { fclose(f); return NULL; }

    int plane_cap = 8;
    scene->planes = malloc(sizeof(plane_t) * (size_t)plane_cap);
    scene->n_planes = 0;

    plane_t *cur = NULL;
    char line[512];

    while (fgets(line, (int)sizeof(line), f)) {
        line[strcspn(line, "\r\n")] = '\0';

        if (strncmp(line, "GRID ", 5) == 0) {
            sscanf(line + 5, "%d %d", &scene->grid_rows, &scene->grid_cols);

        } else if (strncmp(line, "PLANE ", 6) == 0) {
            if (scene->n_planes >= plane_cap) {
                plane_cap *= 2;
                scene->planes = realloc(scene->planes,
                                        sizeof(plane_t) * (size_t)plane_cap);
            }
            cur = &scene->planes[scene->n_planes++];
            memset(cur, 0, sizeof(plane_t));
            sscanf(line + 6, "%d %d %d %d",
                   &cur->y, &cur->x, &cur->rows, &cur->cols);
            cur->cells = calloc((size_t)(cur->rows * cur->cols),
                                sizeof(cell_t));

        } else if (strncmp(line, "BASE ", 5) == 0 && cur) {
            char egc_str[8] = {0};
            unsigned style = 0;
            unsigned long long ch = 0;
            sscanf(line + 5, "%7s %x %llx", egc_str, &style, &ch);
            if (strcmp(egc_str, "_") == 0)
                cur->base.egc[0] = '\0';
            else {
                strncpy(cur->base.egc, egc_str, sizeof(cur->base.egc) - 1);
                cur->base.egc[sizeof(cur->base.egc) - 1] = '\0';
            }
            cur->base.stylemask = (uint16_t)style;
            cur->base.channels  = (uint64_t)ch;

        } else if (strncmp(line, "CELL ", 5) == 0 && cur) {
            int cy = 0, cx = 0;
            char egc_str[8] = {0};
            unsigned style = 0;
            unsigned long long ch = 0;
            sscanf(line + 5, "%d %d %7s %x %llx",
                   &cy, &cx, egc_str, &style, &ch);
            if (cy >= 0 && cy < cur->rows && cx >= 0 && cx < cur->cols) {
                cell_t *cell = &cur->cells[cy * cur->cols + cx];
                if (strcmp(egc_str, "_") == 0)
                    cell->egc[0] = '\0';
                else {
                    strncpy(cell->egc, egc_str, sizeof(cell->egc) - 1);
                    cell->egc[sizeof(cell->egc) - 1] = '\0';
                }
                cell->stylemask = (uint16_t)style;
                cell->channels  = (uint64_t)ch;
            }

        } else if (strncmp(line, "ENDPLANE", 8) == 0) {
            cur = NULL;
        }
    }

    fclose(f);
    return scene;
}

void scene_free(scene_t *scene) {
    if (!scene) return;
    for (int i = 0; i < scene->n_planes; i++)
        free(scene->planes[i].cells);
    free(scene->planes);
    free(scene);
}

/*
 * Output format (one line per cell, space-separated):
 *   y  x  egc_codepoint  fg_r fg_g fg_b  bg_r bg_g bg_b  style_hex
 *
 * egc_codepoint is the decimal value of the first byte of the EGC
 * (all test cases use single-byte ASCII characters).
 * fg/bg components are -1 when the color is the terminal default.
 */
void output_print(const composited_cell_t *output, int rows, int cols) {
    for (int y = 0; y < rows; y++) {
        for (int x = 0; x < cols; x++) {
            const composited_cell_t *c = &output[y * cols + x];
            int egc_code = (unsigned char)(c->egc[0] ? c->egc[0] : ' ');
            printf("%d %d %d %d %d %d %d %d %d %04x\n",
                   y, x, egc_code,
                   c->fg_r, c->fg_g, c->fg_b,
                   c->bg_r, c->bg_g, c->bg_b,
                   (unsigned)c->style);
        }
    }
}
