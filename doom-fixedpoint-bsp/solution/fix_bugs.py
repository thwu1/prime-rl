#!/usr/bin/env python3
"""
Fix all bugs in the BSP map analyser project and implement the DIRHASH stub.
13 issues across 4 files: Makefile, main.c, wad_reader.c, fixed_math.c, bsp.c.
"""


import re

def fix(path, replacements):
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise RuntimeError(f"Pattern not found in {path}: {old!r}")
        content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)


# --- Bug 1: Makefile — doom_math.o conflicts; need bsp.o instead ---
fix('/app/Makefile', [
    ('OBJS = main.o wad_reader.o fixed_math.o doom_math.o',
     'OBJS = main.o wad_reader.o fixed_math.o bsp.o'),
])


# --- Bugs 2-6 in wad_reader.c ---
with open('/app/wad_reader.c') as f:
    src = f.read()

# Bug 2: Remove spurious big-endian byte swap on numlumps
src = src.replace(
    '    /* Byte-swap: WAD files originate on big-endian 68k Nextstations */\n'
    '    wad_hdr.numlumps = ((wad_hdr.numlumps >> 24) & 0xFF)       |\n'
    '                       ((wad_hdr.numlumps >>  8) & 0xFF00)     |\n'
    '                       ((wad_hdr.numlumps <<  8) & 0xFF0000)   |\n'
    '                       ((wad_hdr.numlumps << 24) & 0xFF000000u);\n',
    '')

# Bug 3: Fix off-by-one in directory read loop: wad_nlumps - 1 -> wad_nlumps
src = src.replace('i < wad_nlumps - 1', 'i < wad_nlumps')

# Bug 4: Fix coordinate shift FRACBITS-1 -> FRACBITS
src = src.replace('<< (FRACBITS - 1)', '<< FRACBITS')

# Bug 5: Fix hash shift << 4 -> << 5
src = src.replace('hash << 4)', 'hash << 5)')

# Bug 6: Implement wad_directory_hash (replace stub with FNV-1a)
stub = (
    'uint32_t wad_directory_hash(void)\n'
    '{\n'
    '    /* Not yet implemented — computes FNV-1a over directory entries */\n'
    '    return 0;\n'
    '}'
)
impl = (
    'uint32_t wad_directory_hash(void)\n'
    '{\n'
    '    uint32_t hash = 2166136261u;\n'
    '    for (int i = 0; i < wad_nlumps; i++) {\n'
    '        uint32_t fp = (uint32_t)wad_dir[i].filepos;\n'
    '        for (int b = 0; b < 4; b++) {\n'
    '            hash ^= (fp >> (b * 8)) & 0xFF;\n'
    '            hash *= 16777619u;\n'
    '        }\n'
    '        uint32_t sz = (uint32_t)wad_dir[i].size;\n'
    '        for (int b = 0; b < 4; b++) {\n'
    '            hash ^= (sz >> (b * 8)) & 0xFF;\n'
    '            hash *= 16777619u;\n'
    '        }\n'
    '        for (int j = 0; j < 8; j++) {\n'
    '            hash ^= (uint8_t)wad_dir[i].name[j];\n'
    '            hash *= 16777619u;\n'
    '        }\n'
    '    }\n'
    '    return hash;\n'
    '}'
)
src = src.replace(stub, impl)

with open('/app/wad_reader.c', 'w') as f:
    f.write(src)


# --- Bug 7: main.c — move wad_close() after query processing ---
with open('/app/main.c') as f:
    src = f.read()

# Remove the early wad_close() call
src = src.replace(
    '    bsp_set_data(nodes, num_nodes, subsectors, num_ss);\n'
    '    wad_close();\n',
    '    bsp_set_data(nodes, num_nodes, subsectors, num_ss);\n')

# Add wad_close() after query processing, before free()
src = src.replace(
    '    fclose(qf);\n'
    '    fclose(of);\n'
    '    free(nodes);',
    '    fclose(qf);\n'
    '    fclose(of);\n'
    '    wad_close();\n'
    '    free(nodes);')

with open('/app/main.c', 'w') as f:
    f.write(src)


# --- Bugs 8, 9 in fixed_math.c ---
fix('/app/fixed_math.c', [
    # Bug 8: overflow guard >> 15 -> >> 14
    ('>> 15)', '>> 14)'),
    # Bug 9: swap INT_MAX/INT_MIN back to correct order
    ('INT_MAX : INT_MIN', 'INT_MIN : INT_MAX'),
])


# --- Bugs 10-13 in bsp.c ---
with open('/app/bsp.c') as f:
    src = f.read()

# Bug 10: SlopeDiv threshold 256 -> 512
src = src.replace('den < 256)', 'den < 512)')

# Bug 11: R_PointOnSide sign-bit check: (node->dx ^ dy) -> (node->dy ^ dx)
src = src.replace('(node->dx ^ dy)', '(node->dy ^ dx)')

# Bug 12: R_PointToAngle2 octant 5 formula
src = src.replace('ANG270 + 1 + tantoangle', 'ANG270 - 1 - tantoangle')

# Bug 13: BSP traversal order — swap the two traverse_node calls
src = src.replace(
    '    /* Visit subtrees: back side first, then front side */\n'
    '    traverse_node(bsp->children[side ^ 1], vx, vy);\n'
    '    traverse_node(bsp->children[side],     vx, vy);',
    '    /* Visit subtrees: front side first, then back side */\n'
    '    traverse_node(bsp->children[side],     vx, vy);\n'
    '    traverse_node(bsp->children[side ^ 1], vx, vy);')

with open('/app/bsp.c', 'w') as f:
    f.write(src)

print("All 13 issues fixed.")
