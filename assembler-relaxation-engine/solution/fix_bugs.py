#!/usr/bin/env python3
"""Patch assembler source to fix three bugs in layout.c and parser.c."""

# --- Fix bugs in layout.c ---
with open('/app/layout.c') as f:
    src = f.read()

# Bug 1: Alignment padding must handle already-aligned offsets.
# When offset % alignment == 0, the expression (a - 0) gives 'a' instead of 0.
# Fix: wrap in outer modulo to produce 0 when already aligned.
src = src.replace(
    'int padding = a - (offset % a);',
    'int padding = (a - (offset % a)) % a;'
)

# Bug 2: Jump displacement must be measured from the END of the jump
# instruction, not its start. The size (2 or 6) must be included.
src = src.replace(
    'int disp = target - it->offset;',
    'int disp = target - (it->offset + it->size);'
)

with open('/app/layout.c', 'w') as f:
    f.write(src)

# --- Fix bug in parser.c ---
with open('/app/parser.c') as f:
    src = f.read()

# Bug 3: When a label and statement share a line (e.g., "A: inst 2"),
# the label's item_index is recorded AFTER the item is added, making
# it point to the wrong (next) item. Save the index before processing.
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
