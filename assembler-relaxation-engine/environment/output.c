#include <stdio.h>
#include "assembler.h"

void print_json(const Program *prog, const LayoutResult *result) {
    printf("{\n");
    printf("  \"total_size\": %d,\n", result->total_size);
    printf("  \"iterations\": %d,\n", result->iterations);

    /* Labels */
    printf("  \"labels\": {");
    int first = 1;
    for (int i = 0; i < prog->num_labels; i++) {
        if (!first) printf(",");
        printf("\n    \"%s\": %d", prog->labels[i].name, prog->labels[i].offset);
        first = 0;
    }
    if (prog->num_labels) printf("\n  ");
    printf("},\n");

    /* Jumps */
    printf("  \"jumps\": [");
    first = 1;
    for (int i = 0; i < prog->num_items; i++) {
        const Item *it = &prog->items[i];
        if (it->type != ITEM_JUMP) continue;
        if (!first) printf(",");
        printf("\n    {\"line\": %d, \"target\": \"%s\", \"offset\": %d, \"size\": %d, \"relaxed\": %s}",
               it->line, it->target, it->offset, it->size,
               it->relaxed ? "true" : "false");
        first = 0;
    }
    if (!first) printf("\n  ");
    printf("]\n}\n");
}
