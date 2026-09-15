#include "assembler.h"
#include <string.h>

/* Find offset of a label by name, or -1 if not found */
static int label_offset(const Program *prog, const char *name) {
    for (int i = 0; i < prog->num_labels; i++) {
        if (strcmp(prog->labels[i].name, name) == 0)
            return prog->labels[i].offset;
    }
    return -1;
}

/*
 * Compute byte offsets for all items and labels.
 * Returns total program size.
 */
static int compute_layout(Program *prog) {
    int offset = 0;

    for (int idx = 0; idx < prog->num_items; idx++) {
        /* Resolve labels at this position */
        for (int l = 0; l < prog->num_labels; l++) {
            if (prog->labels[l].item_index == idx)
                prog->labels[l].offset = offset;
        }

        Item *it = &prog->items[idx];
        it->offset = offset;

        switch (it->type) {
        case ITEM_INST:
        case ITEM_FILL:
            it->size = it->fixed_size;
            offset += it->size;
            break;

        case ITEM_JUMP:
            it->size = it->relaxed ? 6 : 2;
            offset += it->size;
            break;

        case ITEM_ALIGN: {
            int a = it->alignment;
            int padding = a - (offset % a);
            it->size = padding;
            offset += padding;
            break;
        }
        }
    }

    /* End-of-program labels */
    for (int l = 0; l < prog->num_labels; l++) {
        if (prog->labels[l].item_index == prog->num_items)
            prog->labels[l].offset = offset;
    }

    return offset;
}

/*
 * Iterative jump relaxation: switch short jumps to long form
 * when their displacement exceeds the short-range limit.
 */
void relax_layout(Program *prog, LayoutResult *result) {
    result->iterations = 0;
    result->total_size = compute_layout(prog);

    int changed = 0;
    for (int i = 0; i < prog->num_items; i++) {
        Item *it = &prog->items[i];
        if (it->type != ITEM_JUMP || it->relaxed)
            continue;

        int target = label_offset(prog, it->target);
        int disp = target - it->offset;

        if (disp < -128 || disp > 127) {
            it->relaxed = true;
            changed = 1;
        }
    }

    if (changed) {
        result->iterations = 1;
        result->total_size = compute_layout(prog);
    }
}
