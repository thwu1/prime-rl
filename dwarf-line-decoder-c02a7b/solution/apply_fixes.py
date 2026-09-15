#!/usr/bin/env python3
"""
Apply targeted fixes to the bugs in /app/dwarf_cfi.c.

"""

import sys

PATH = "/app/dwarf_cfi.c"

with open(PATH, "r") as f:
    src = f.read()

original = src
applied = []

# ── Fix 1: SLEB128 sign extension ──────────────────────────────────
# The sign bit in LEB128 is bit 6 of the last byte, not bit 7.
old = ("if ((shift < 64) && (byte & 0x80)) {\n"
       "        result |= -(1LL << shift);")
new = ("if ((shift < 64) && (byte & 0x40)) {\n"
       "        result |= -(1LL << shift);")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("SLEB128 sign extension (bit 6)")

# ── Fix 2: Augmentation 'z' data not skipped ──────────────────────
old = ('            if (cie->augmentation[0] == \'z\') {\n'
       '                uint64_t aug_len = read_uleb128(&p, entry_end);\n'
       '                /* augmentation data bytes follow -- skip them */\n'
       '                (void)aug_len;\n'
       '            }')
new = ('            if (cie->augmentation[0] == \'z\') {\n'
       '                uint64_t aug_len = read_uleb128(&p, entry_end);\n'
       '                /* skip augmentation data bytes */\n'
       '                p += aug_len;\n'
       '            }')
if old in src:
    src = src.replace(old, new, 1)
    applied.append("augmentation 'z' data skip")

# ── Fix 3: DW_CFA_offset uses data_alignment_factor ───────────────
# Affects DW_CFA_offset (high-2-bit), DW_CFA_offset_extended, DW_CFA_val_offset
old = "row->regs[reg].operand = (int64_t)(factored * (uint64_t)code_align);"
new = "row->regs[reg].operand = (int64_t)factored * data_align;"
count = src.count(old)
if count > 0:
    src = src.replace(old, new)
    applied.append(f"unsigned factored offset alignment ({count} instances)")

# ── Fix 4: DW_CFA_advance_loc factoring ───────────────────────────
# advance_loc (high-2-bit form)
old = ("            /* DW_CFA_advance_loc: delta in low 6 bits */\n"
       "            uint64_t delta = low6;\n"
       "            *loc += delta;")
new = ("            /* DW_CFA_advance_loc: delta in low 6 bits */\n"
       "            uint64_t delta = (uint64_t)low6 * code_align;\n"
       "            *loc += delta;")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("advance_loc high-2-bit factoring")

# advance_loc1
old = ("            case DW_CFA_advance_loc1: {\n"
       "                uint8_t delta = read_u8(&p, end);\n"
       "                *loc += delta;")
new = ("            case DW_CFA_advance_loc1: {\n"
       "                uint8_t delta = read_u8(&p, end);\n"
       "                *loc += (uint64_t)delta * code_align;")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("advance_loc1 factoring")

# advance_loc2
old = ("            case DW_CFA_advance_loc2: {\n"
       "                uint16_t delta = read_u16(&p, end);\n"
       "                *loc += delta;")
new = ("            case DW_CFA_advance_loc2: {\n"
       "                uint16_t delta = read_u16(&p, end);\n"
       "                *loc += (uint64_t)delta * code_align;")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("advance_loc2 factoring")

# advance_loc4
old = ("            case DW_CFA_advance_loc4: {\n"
       "                uint32_t delta = read_u32(&p, end);\n"
       "                *loc += delta;")
new = ("            case DW_CFA_advance_loc4: {\n"
       "                uint32_t delta = read_u32(&p, end);\n"
       "                *loc += (uint64_t)delta * code_align;")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("advance_loc4 factoring")

# ── Fix 5: remember/restore state uses LIFO (stack) ───────────────
old = ("static bool pop_state(StateStack *stk, RuleRow *row)\n"
       "{\n"
       "    if (stk->read_pos >= stk->count) {\n"
       "        fprintf(stderr, \"warning: state stack underflow\\n\");\n"
       "        return false;\n"
       "    }\n"
       "    copy_rule_row(row, &stk->rows[stk->read_pos]);\n"
       "    stk->read_pos++;\n"
       "    return true;\n"
       "}")
new = ("static bool pop_state(StateStack *stk, RuleRow *row)\n"
       "{\n"
       "    if (stk->count <= 0) {\n"
       "        fprintf(stderr, \"warning: state stack underflow\\n\");\n"
       "        return false;\n"
       "    }\n"
       "    stk->count--;\n"
       "    copy_rule_row(row, &stk->rows[stk->count]);\n"
       "    return true;\n"
       "}")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("remember/restore LIFO semantics")

# ── Fix 6: FDE inherits CIE initial rules ─────────────────────────
old = ("            /* set up rule row -- start from empty, not CIE initial rules */\n"
       "            RuleRow row;\n"
       "            init_rule_row(&row);")
new = ("            /* set up rule row from CIE initial rules */\n"
       "            RuleRow row;\n"
       "            copy_rule_row(&row, &cie->initial_row);")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("FDE inherits CIE initial rules")

# Also pass cie_init for DW_CFA_restore in FDE
old = ("            /* execute FDE instructions */\n"
       "            execute_cfi(p, entry_end,\n"
       "                        cie->code_alignment_factor,\n"
       "                        cie->data_alignment_factor,\n"
       "                        fde_addr_sz,\n"
       "                        &row, &stk, &loc, out,\n"
       "                        NULL, true);")
new = ("            /* execute FDE instructions */\n"
       "            execute_cfi(p, entry_end,\n"
       "                        cie->code_alignment_factor,\n"
       "                        cie->data_alignment_factor,\n"
       "                        fde_addr_sz,\n"
       "                        &row, &stk, &loc, out,\n"
       "                        &cie->initial_row, true);")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("FDE passes cie_init for DW_CFA_restore")

# ── Fix 7: 64-bit DWARF CIE_id check ─────────────────────────────
# In 64-bit DWARF format, CIE_id is 0xFFFFFFFFFFFFFFFF (8 bytes),
# not 0xFFFFFFFF (4 bytes).
old = "        bool is_cie = (cie_id == 0xffffffff);"
new = ("        bool is_cie = dwarf64\n"
       "            ? (cie_id == 0xffffffffffffffffULL)\n"
       "            : (cie_id == 0xffffffff);")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("64-bit DWARF CIE_id check")

# ── Fix 8: DW_CFA_offset_extended_sf uses data_align ──────────────
old = ("                    row->regs[reg].operand = off * (int64_t)code_align;")
new = ("                    row->regs[reg].operand = off * data_align;")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("offset_extended_sf uses data_align")

# ── Fix 9: DW_CFA_def_cfa_sf multiplies by data_align ─────────────
old = ("            case DW_CFA_def_cfa_sf: {\n"
       "                row->cfa.reg    = (uint32_t)read_uleb128(&p, end);\n"
       "                int64_t off     = read_sleb128(&p, end);\n"
       "                row->cfa.offset = off;\n"
       "                row->cfa.is_expr = false;")
new = ("            case DW_CFA_def_cfa_sf: {\n"
       "                row->cfa.reg    = (uint32_t)read_uleb128(&p, end);\n"
       "                int64_t off     = read_sleb128(&p, end);\n"
       "                row->cfa.offset = off * data_align;\n"
       "                row->cfa.is_expr = false;")
if old in src:
    src = src.replace(old, new, 1)
    applied.append("def_cfa_sf multiplies by data_align")

if src == original:
    print("WARNING: no changes were applied", file=sys.stderr)
    sys.exit(1)

with open(PATH, "w") as f:
    f.write(src)

print(f"Applied {len(applied)} fixes:")
for fix in applied:
    print(f"  - {fix}")
