#!/usr/bin/env python3
"""Fix assembler bugs in layout.c and parser.c.

"""

# --- Write corrected layout.c ---
layout_c = r'''#include "assembler.h"
#include <string.h>

static int label_offset(const Program *prog, const char *name) {
    for (int i = 0; i < prog->num_labels; i++) {
        if (strcmp(prog->labels[i].name, name) == 0)
            return prog->labels[i].offset;
    }
    return -1;
}

static int compute_layout(Program *prog) {
    int offset = 0;

    for (int idx = 0; idx < prog->num_items; idx++) {
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
            it->size = it->relaxed ? (it->is_cond ? 6 : 5) : 2;
            offset += it->size;
            break;
        case ITEM_ALIGN: {
            int a = it->alignment;
            int padding = (a - (offset % a)) % a;
            it->size = padding;
            offset += padding;
            break;
        }
        }
    }

    for (int l = 0; l < prog->num_labels; l++) {
        if (prog->labels[l].item_index == prog->num_items)
            prog->labels[l].offset = offset;
    }

    return offset;
}

void relax_layout(Program *prog, LayoutResult *result) {
    result->iterations = 0;

    for (;;) {
        int total = compute_layout(prog);
        int changed = 0;

        for (int i = 0; i < prog->num_items; i++) {
            Item *it = &prog->items[i];
            if (it->type != ITEM_JUMP || it->relaxed)
                continue;

            int target = label_offset(prog, it->target);
            int disp = target - (it->offset + it->size);

            if (disp < -128 || disp > 127) {
                it->relaxed = true;
                changed = 1;
            }
        }

        if (!changed) {
            result->total_size = total;
            return;
        }
        result->iterations++;
    }
}
'''

with open('/app/layout.c', 'w') as f:
    f.write(layout_c)

# --- Fix inline-label bug in parser.c ---
with open('/app/parser.c') as f:
    src = f.read()

src = src.replace(
    '        /* --- Statement parsing --- */\n        if (*text) {',
    '        int label_item_idx = prog->num_items;\n\n        /* --- Statement parsing --- */\n        if (*text) {'
)
src = src.replace(
    '            lb->item_index = prog->num_items;',
    '            lb->item_index = label_item_idx;'
)

with open('/app/parser.c', 'w') as f:
    f.write(src)
