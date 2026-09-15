#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "compositor.h"
#include "scene_io.h"
#include "rasterizer.h"

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr,
            "Usage:\n"
            "  %s <scene>            Text cell output\n"
            "  %s -r <scene>         Full rasterize (ANSI sequences)\n"
            "  %s -d <prev> <curr>   Diff rasterize\n",
            argv[0], argv[0], argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "-r") == 0 && argc == 3) {
        /* ── Full rasterize mode ──────────────────────────────── */
        scene_t *scene = scene_parse(argv[2]);
        if (!scene) { fprintf(stderr, "Error: parse failed\n"); return 1; }

        int n = scene->grid_rows * scene->grid_cols;
        composited_cell_t *out = calloc((size_t)n, sizeof(composited_cell_t));
        composite_scene(scene, out);

        raster_buf_t rb;
        raster_init(&rb);
        rasterize_full(out, scene->grid_rows, scene->grid_cols, &rb);
        fwrite(rb.buf, 1, rb.len, stdout);

        raster_free(&rb);
        free(out);
        scene_free(scene);
        return 0;

    } else if (strcmp(argv[1], "-d") == 0 && argc == 4) {
        /* ── Diff rasterize mode ──────────────────────────────── */
        scene_t *s1 = scene_parse(argv[2]);
        scene_t *s2 = scene_parse(argv[3]);
        if (!s1 || !s2) { fprintf(stderr, "Error: parse failed\n"); return 1; }
        if (s1->grid_rows != s2->grid_rows ||
            s1->grid_cols != s2->grid_cols) {
            fprintf(stderr, "Error: grid dimensions must match\n");
            return 1;
        }

        int n = s1->grid_rows * s1->grid_cols;
        composited_cell_t *o1 = calloc((size_t)n, sizeof(composited_cell_t));
        composited_cell_t *o2 = calloc((size_t)n, sizeof(composited_cell_t));
        composite_scene(s1, o1);
        composite_scene(s2, o2);

        raster_buf_t rb;
        raster_init(&rb);
        rasterize_diff(o1, o2, s1->grid_rows, s1->grid_cols, &rb);
        fwrite(rb.buf, 1, rb.len, stdout);

        raster_free(&rb);
        free(o1); free(o2);
        scene_free(s1); scene_free(s2);
        return 0;

    } else if (argc == 2) {
        /* ── Text output mode ─────────────────────────────────── */
        scene_t *scene = scene_parse(argv[1]);
        if (!scene) {
            fprintf(stderr, "Error: failed to parse '%s'\n", argv[1]);
            return 1;
        }

        int n = scene->grid_rows * scene->grid_cols;
        composited_cell_t *out = calloc((size_t)n, sizeof(composited_cell_t));
        composite_scene(scene, out);
        output_print(out, scene->grid_rows, scene->grid_cols);

        free(out);
        scene_free(scene);
        return 0;

    } else {
        fprintf(stderr, "Invalid arguments\n");
        return 1;
    }
}
