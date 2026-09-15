#!/usr/bin/env python3
"""
Implement all optimization passes and compaction in /app/src/optimizer.c.

Replaces the six stubbed functions with working implementations.

"""

SRC = "/app/src/optimizer.c"


def replace_function_body(code, func_sig_prefix, new_body):
    """Replace a C function body identified by a unique signature prefix."""
    idx = code.find(func_sig_prefix)
    if idx < 0:
        raise ValueError(f"Function not found: {func_sig_prefix!r}")

    # Find the opening brace of the function body
    brace_idx = code.index("{", idx)

    # Count braces to find matching close
    depth = 1
    i = brace_idx + 1
    while depth > 0 and i < len(code):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
        i += 1

    return code[:brace_idx] + "{\n" + new_body + "\n}\n" + code[i:]


with open(SRC, "r") as f:
    code = f.read()

# ===================================================================
# 1. opt_constant_fold
# ===================================================================
code = replace_function_body(code, "static int opt_constant_fold(Program *prog)", r"""
    int changed = 0;
    for (int i = 0; i < prog->count; i++) {
        if (prog->insns[i].deleted || prog->insns[i].opcode != OP_push_i32)
            continue;
        /* find next non-deleted instruction */
        int j = i + 1;
        while (j < prog->count && prog->insns[j].deleted) j++;
        if (j >= prog->count || prog->insns[j].opcode != OP_push_i32)
            continue;
        /* find the one after that */
        int k = j + 1;
        while (k < prog->count && prog->insns[k].deleted) k++;
        if (k >= prog->count)
            continue;
        uint8_t aop = prog->insns[k].opcode;
        if (aop != OP_add && aop != OP_sub && aop != OP_mul)
            continue;

        int32_t x = read_i32(prog->insns[i].operand);
        int32_t y = read_i32(prog->insns[j].operand);
        int32_t r;
        if (aop == OP_add)      r = x + y;
        else if (aop == OP_sub) r = x - y;
        else                    r = x * y;

        write_i32(prog->insns[i].operand, r);
        prog->insns[j].deleted = true;
        prog->insns[k].deleted = true;
        changed++;
    }
    return changed;
""")

# ===================================================================
# 2. opt_dead_branches
# ===================================================================
code = replace_function_body(code, "static int opt_dead_branches(Program *prog)", r"""
    int changed = 0;
    for (int i = 0; i < prog->count; i++) {
        if (prog->insns[i].deleted) continue;
        uint8_t op1 = prog->insns[i].opcode;
        if (op1 != OP_push_true && op1 != OP_push_false) continue;

        int j = i + 1;
        while (j < prog->count && prog->insns[j].deleted) j++;
        if (j >= prog->count) continue;
        uint8_t op2 = prog->insns[j].opcode;
        if (op2 != OP_if_false && op2 != OP_if_true) continue;

        bool val = (op1 == OP_push_true);
        bool takes_branch = (val && op2 == OP_if_true) ||
                            (!val && op2 == OP_if_false);

        prog->insns[i].deleted = true;
        if (takes_branch) {
            /* convert conditional to unconditional */
            prog->insns[j].opcode = OP_goto_op;
        } else {
            /* branch never taken — delete it entirely */
            prog->insns[j].deleted = true;
        }
        changed++;
    }
    return changed;
""")

# ===================================================================
# 3. opt_dead_code
# ===================================================================
code = replace_function_body(code, "static int opt_dead_code(Program *prog)", r"""
    /* build set of live branch targets */
    bool *is_target = calloc((size_t)(prog->orig_code_len + 1), sizeof(bool));
    if (!is_target) return 0;
    for (int i = 0; i < prog->count; i++) {
        Insn *insn = &prog->insns[i];
        if (insn->deleted) continue;
        if (insn->opcode == OP_if_false || insn->opcode == OP_if_true ||
            insn->opcode == OP_goto_op  || insn->opcode == OP_catch) {
            int32_t rel = read_i32(insn->operand);
            int target = insn->orig_offset + rel;
            if (target >= 0 && target <= prog->orig_code_len)
                is_target[target] = true;
        }
    }

    int changed = 0;
    bool dead = false;
    for (int i = 0; i < prog->count; i++) {
        Insn *insn = &prog->insns[i];
        if (insn->deleted) continue;

        if (dead) {
            if (is_target[insn->orig_offset]) {
                dead = false;
            } else {
                insn->deleted = true;
                changed++;
                continue;
            }
        }

        if (insn->opcode == OP_return_val  || insn->opcode == OP_return_undef ||
            insn->opcode == OP_throw_op    || insn->opcode == OP_goto_op) {
            dead = true;
        }
    }

    free(is_target);
    return changed;
""")

# ===================================================================
# 4. opt_thread_gotos
# ===================================================================
code = replace_function_body(code, "static int opt_thread_gotos(Program *prog)", r"""
    /* build offset → instruction index map */
    int map_sz = prog->orig_code_len;
    int *off2idx = malloc((size_t)map_sz * sizeof(int));
    if (!off2idx) return 0;
    memset(off2idx, 0xFF, (size_t)map_sz * sizeof(int)); /* -1 */
    for (int i = 0; i < prog->count; i++) {
        if (!prog->insns[i].deleted && prog->insns[i].orig_offset < map_sz)
            off2idx[prog->insns[i].orig_offset] = i;
    }

    int changed = 0;
    for (int i = 0; i < prog->count; i++) {
        Insn *insn = &prog->insns[i];
        if (insn->deleted) continue;
        if (insn->opcode != OP_goto_op  && insn->opcode != OP_if_false &&
            insn->opcode != OP_if_true  && insn->opcode != OP_catch)
            continue;

        int32_t rel = read_i32(insn->operand);
        int target_off = insn->orig_offset + rel;

        int depth = 0;
        while (depth < 100) {
            if (target_off < 0 || target_off >= map_sz) break;
            int tidx = off2idx[target_off];
            if (tidx < 0) break;
            if (prog->insns[tidx].deleted) break;
            if (prog->insns[tidx].opcode != OP_goto_op) break;

            int32_t next_rel = read_i32(prog->insns[tidx].operand);
            target_off = prog->insns[tidx].orig_offset + next_rel;
            depth++;
        }

        int32_t new_rel = target_off - insn->orig_offset;
        if (new_rel != rel) {
            write_i32(insn->operand, new_rel);
            changed++;
        }
    }

    free(off2idx);
    return changed;
""")

# ===================================================================
# 5. opt_push_drop
# ===================================================================
code = replace_function_body(code, "static int opt_push_drop(Program *prog)", r"""
    int changed = 0;
    for (int i = 0; i < prog->count; i++) {
        Insn *insn = &prog->insns[i];
        if (insn->deleted) continue;

        uint8_t op = insn->opcode;
        if (op != OP_push_i32   && op != OP_push_const &&
            op != OP_push_true  && op != OP_push_false &&
            op != OP_undefined  && op != OP_null_val   && op != OP_object)
            continue;

        int j = i + 1;
        while (j < prog->count && prog->insns[j].deleted) j++;
        if (j >= prog->count) break;

        if (prog->insns[j].opcode == OP_drop) {
            insn->deleted = true;
            prog->insns[j].deleted = true;
            changed++;
        }
    }
    return changed;
""")

# ===================================================================
# 6. compact_and_rewrite
# ===================================================================
code = replace_function_body(code, "static bool compact_and_rewrite(Program *prog)", r"""
    /* 1. Build offset map: orig_offset → new byte offset */
    int *offset_map = calloc((size_t)(prog->orig_code_len + 1), sizeof(int));
    if (!offset_map) return false;

    int new_off = 0;
    for (int i = 0; i < prog->count; i++) {
        offset_map[prog->insns[i].orig_offset] = new_off;
        if (!prog->insns[i].deleted)
            new_off += prog->insns[i].size;
    }
    offset_map[prog->orig_code_len] = new_off;

    /* 2. Rewrite branch operands */
    for (int i = 0; i < prog->count; i++) {
        Insn *insn = &prog->insns[i];
        if (insn->deleted) continue;

        if (insn->opcode == OP_if_false || insn->opcode == OP_if_true ||
            insn->opcode == OP_goto_op  || insn->opcode == OP_catch) {
            int32_t old_rel = read_i32(insn->operand);
            int old_target = insn->orig_offset + old_rel;
            if (old_target < 0 || old_target > prog->orig_code_len) {
                free(offset_map);
                return false;
            }
            int32_t new_rel = offset_map[old_target] -
                              offset_map[insn->orig_offset];
            write_i32(insn->operand, new_rel);
        }
    }

    /* 3. Remove deleted instructions from array */
    int j = 0;
    for (int i = 0; i < prog->count; i++) {
        if (!prog->insns[i].deleted) {
            prog->insns[j] = prog->insns[i];
            j++;
        }
    }
    prog->count = j;

    free(offset_map);
    return true;
""")

with open(SRC, "w") as f:
    f.write(code)

print("optimizer.c patched with all optimization passes")
