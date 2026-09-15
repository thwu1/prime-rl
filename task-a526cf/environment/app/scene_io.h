#ifndef SCENE_IO_H
#define SCENE_IO_H

#include "compositor.h"

/* Parse a scene description from a text file.  Returns NULL on error. */
scene_t *scene_parse(const char *filename);

/* Free all memory owned by a scene. */
void scene_free(scene_t *scene);

/* Print composited output to stdout (one line per cell). */
void output_print(const composited_cell_t *output, int rows, int cols);

#endif /* SCENE_IO_H */
