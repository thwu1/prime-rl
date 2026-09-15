#!/usr/bin/env python3
"""MiniCalc bytecode optimizer.

Implements six optimization passes applied iteratively to a fixed point:
1. Constant folding
2. Constant propagation
3. Dead store elimination
4. Unreachable code elimination
5. Algebraic identity simplification
6. Peephole optimization

Jump targets are converted to labels before optimization and resolved
back to absolute indices afterward.

"""

import json
import sys
import copy

# Arithmetic opcodes that can be constant-folded
ARITH_OPS = {"ADD", "SUB", "MUL", "DIV", "MOD"}
CMP_OPS = {"EQ", "NE", "LT", "LE", "GT", "GE"}
LOGIC_OPS = {"AND", "OR"}
FOLDABLE_BINARY = ARITH_OPS | CMP_OPS | LOGIC_OPS


def eval_binary(op, a, b):
    """Evaluate a binary operation on two integer constants."""
    if op == "ADD":
        return a + b
    elif op == "SUB":
        return a - b
    elif op == "MUL":
        return a * b
    elif op == "DIV":
        if b == 0:
            return None
        return int(a / b)
    elif op == "MOD":
        if b == 0:
            return None
        result = abs(a) % abs(b)
        if a < 0:
            result = -result
        return result
    elif op == "EQ":
        return 1 if a == b else 0
    elif op == "NE":
        return 1 if a != b else 0
    elif op == "LT":
        return 1 if a < b else 0
    elif op == "LE":
        return 1 if a <= b else 0
    elif op == "GT":
        return 1 if a > b else 0
    elif op == "GE":
        return 1 if a >= b else 0
    elif op == "AND":
        return 1 if (a != 0 and b != 0) else 0
    elif op == "OR":
        return 1 if (a != 0 or b != 0) else 0
    return None


# ---------------------------------------------------------------------------
# Label management: convert between absolute indices and label-based jumps
# ---------------------------------------------------------------------------

_label_counter = 0


def _new_label():
    global _label_counter
    _label_counter += 1
    return f"__OPT_L{_label_counter}"


def add_labels(code):
    """Convert absolute jump targets to label references, inserting LABEL instructions."""
    targets = set()
    for instr in code:
        if instr[0] in ("JMP", "JMP_FALSE") and isinstance(instr[1], int):
            targets.add(instr[1])

    # Create label names for each target index
    label_map = {}
    for t in targets:
        label_map[t] = _new_label()

    # Insert labels and update jumps
    labeled = []
    for i, instr in enumerate(code):
        if i in label_map:
            labeled.append(["LABEL", label_map[i]])
        if instr[0] in ("JMP", "JMP_FALSE") and isinstance(instr[1], int):
            labeled.append([instr[0], label_map[instr[1]]])
        else:
            labeled.append(list(instr))

    # Handle labels at the end (jump past last instruction)
    max_idx = len(code)
    if max_idx in label_map:
        labeled.append(["LABEL", label_map[max_idx]])

    return labeled


def remove_labels(code):
    """Resolve label references to absolute indices and remove LABEL instructions."""
    labels = {}
    real_idx = 0
    for instr in code:
        if instr[0] == "LABEL":
            labels[instr[1]] = real_idx
        else:
            real_idx += 1

    result = []
    for instr in code:
        if instr[0] == "LABEL":
            continue
        if instr[0] in ("JMP", "JMP_FALSE") and isinstance(instr[1], str):
            result.append([instr[0], labels[instr[1]]])
        else:
            result.append(list(instr))
    return result


# ---------------------------------------------------------------------------
# Pass 1: Constant Folding
# ---------------------------------------------------------------------------

def constant_fold(code):
    """Fold PUSH_INT a, PUSH_INT b, <op> into PUSH_INT result.
    Also fold PUSH_INT a, NEG and PUSH_INT a, NOT."""
    changed = False
    new_code = []
    i = 0
    while i < len(code):
        # Binary constant folding
        if (i + 2 < len(code) and
                new_code and len(new_code) >= 1 and
                new_code[-1][0] == "PUSH_INT" and
                code[i][0] == "PUSH_INT" and
                code[i + 1][0] in FOLDABLE_BINARY):
            a = new_code[-1][1]
            b = code[i][1]
            op = code[i + 1][0]
            result = eval_binary(op, a, b)
            if result is not None:
                new_code[-1] = ["PUSH_INT", result]
                i += 2
                changed = True
                continue

        # Check pattern starting fresh (not relying on new_code)
        if (i + 2 < len(code) and
                code[i][0] == "PUSH_INT" and
                code[i + 1][0] == "PUSH_INT" and
                code[i + 2][0] in FOLDABLE_BINARY):
            a = code[i][1]
            b = code[i + 1][1]
            op = code[i + 2][0]
            result = eval_binary(op, a, b)
            if result is not None:
                new_code.append(["PUSH_INT", result])
                i += 3
                changed = True
                continue

        # Unary constant folding: PUSH_INT a, NEG
        if (i + 1 < len(code) and
                code[i][0] == "PUSH_INT" and code[i + 1][0] == "NEG"):
            new_code.append(["PUSH_INT", -code[i][1]])
            i += 2
            changed = True
            continue

        # Unary: PUSH_INT a, NOT
        if (i + 1 < len(code) and
                code[i][0] == "PUSH_INT" and code[i + 1][0] == "NOT"):
            new_code.append(["PUSH_INT", 1 if code[i][1] == 0 else 0])
            i += 2
            changed = True
            continue

        # Also fold from end of new_code
        if (new_code and new_code[-1][0] == "PUSH_INT" and
                code[i][0] == "NEG"):
            new_code[-1] = ["PUSH_INT", -new_code[-1][1]]
            i += 1
            changed = True
            continue

        if (new_code and new_code[-1][0] == "PUSH_INT" and
                code[i][0] == "NOT"):
            new_code[-1] = ["PUSH_INT", 1 if new_code[-1][1] == 0 else 0]
            i += 1
            changed = True
            continue

        # Fold binary when left operand is in new_code
        if (new_code and new_code[-1][0] == "PUSH_INT" and
                code[i][0] in FOLDABLE_BINARY):
            # Check if there's a PUSH_INT two back in new_code
            if len(new_code) >= 2 and new_code[-2][0] == "PUSH_INT":
                a = new_code[-2][1]
                b = new_code[-1][1]
                op = code[i][0]
                result = eval_binary(op, a, b)
                if result is not None:
                    new_code.pop()
                    new_code[-1] = ["PUSH_INT", result]
                    i += 1
                    changed = True
                    continue

        new_code.append(list(code[i]))
        i += 1

    return new_code, changed


# ---------------------------------------------------------------------------
# Pass 2: Constant Propagation
# ---------------------------------------------------------------------------

def constant_propagate(code):
    """Replace LOAD x with PUSH_INT v when x is known to be constant v."""
    changed = False
    known = {}  # var_name -> constant_value
    new_code = []

    for i, instr in enumerate(code):
        if instr[0] == "LABEL":
            # Control flow merge point: invalidate all
            known = {}
            new_code.append(list(instr))
        elif instr[0] == "STORE":
            var = instr[1]
            # Check if the value being stored is a known constant
            if new_code and new_code[-1][0] == "PUSH_INT":
                known[var] = new_code[-1][1]
            else:
                # Unknown value, invalidate this variable
                if var in known:
                    del known[var]
            new_code.append(list(instr))
        elif instr[0] == "LOAD" and instr[1] in known:
            new_code.append(["PUSH_INT", known[instr[1]]])
            changed = True
        elif instr[0] in ("JMP", "JMP_FALSE"):
            # At a branch, invalidate everything (conservative)
            known = {}
            new_code.append(list(instr))
        elif instr[0] in ("CALL", "RET", "HALT"):
            known = {}
            new_code.append(list(instr))
        else:
            new_code.append(list(instr))

    return new_code, changed


# ---------------------------------------------------------------------------
# Pass 3: Dead Store Elimination
# ---------------------------------------------------------------------------

def dead_store_eliminate(code):
    """Remove stores that are overwritten before being read."""
    changed = False
    new_code = list(code)

    # Find dead stores within straight-line code
    stores_to_remove = set()
    for i in range(len(new_code)):
        if new_code[i][0] == "STORE":
            var = new_code[i][1]
            # Look ahead: is this var read before being stored again?
            is_dead = False
            for j in range(i + 1, len(new_code)):
                op = new_code[j][0]
                if op in ("JMP", "JMP_FALSE", "CALL", "RET", "HALT", "LABEL"):
                    break  # Control flow: conservatively stop
                if op == "LOAD" and new_code[j][1] == var:
                    break  # Variable is read
                if op == "STORE" and new_code[j][1] == var:
                    is_dead = True
                    break  # Variable is overwritten
            if is_dead:
                stores_to_remove.add(i)

    if not stores_to_remove:
        return new_code, False

    # Remove dead stores: replace STORE with POP, and try to remove
    # the preceding PUSH_INT if it's the immediate predecessor
    result = []
    skip_next = set()
    for i in range(len(new_code)):
        if i in skip_next:
            continue
        if i in stores_to_remove:
            # Check if preceding instruction is PUSH_INT (the stored value)
            if result and result[-1][0] == "PUSH_INT":
                result.pop()  # Remove the PUSH_INT too
            else:
                result.append(["POP"])  # Can't remove value computation, just pop
            changed = True
        else:
            result.append(list(new_code[i]))

    return result, changed


# ---------------------------------------------------------------------------
# Pass 4: Unreachable Code Elimination
# ---------------------------------------------------------------------------

def unreachable_code_eliminate(code):
    """Remove instructions after JMP/RET/HALT that aren't jump targets."""
    # Find all label names that are jump targets
    jump_labels = set()
    for instr in code:
        if instr[0] in ("JMP", "JMP_FALSE") and isinstance(instr[1], str):
            jump_labels.add(instr[1])

    changed = False
    new_code = []
    unreachable = False

    for instr in code:
        if instr[0] == "LABEL" and instr[1] in jump_labels:
            unreachable = False
            new_code.append(list(instr))
            continue

        if unreachable:
            # Skip this instruction (it's unreachable)
            if instr[0] != "LABEL":
                changed = True
                continue
            else:
                # Keep labels even if unreachable (they might be targets)
                new_code.append(list(instr))
                continue

        new_code.append(list(instr))
        if instr[0] in ("JMP", "RET", "HALT"):
            unreachable = True

    return new_code, changed


# ---------------------------------------------------------------------------
# Pass 5: Algebraic Identity Simplification
# ---------------------------------------------------------------------------

def algebraic_simplify(code):
    """Remove identity operations: x+0, x-0, x*1 -> x; x*0 -> 0."""
    changed = False
    new_code = []

    for i, instr in enumerate(code):
        # Check for patterns ending at current instruction
        if (len(new_code) >= 2 and
                new_code[-1][0] == "PUSH_INT"):
            const_val = new_code[-1][1]
            op = instr[0]

            # x + 0 -> x
            if op == "ADD" and const_val == 0:
                new_code.pop()  # Remove PUSH_INT 0
                # Don't append ADD
                changed = True
                continue

            # x - 0 -> x
            if op == "SUB" and const_val == 0:
                new_code.pop()
                changed = True
                continue

            # x * 1 -> x
            if op == "MUL" and const_val == 1:
                new_code.pop()
                changed = True
                continue

            # x * 0 -> pop x, push 0
            if op == "MUL" and const_val == 0:
                # Keep PUSH_INT 0, but we need to discard the value below it
                # Replace the two items with: POP, PUSH_INT 0
                new_code.pop()  # Remove PUSH_INT 0
                new_code.append(["POP"])
                new_code.append(["PUSH_INT", 0])
                changed = True
                continue

        new_code.append(list(instr))

    return new_code, changed


# ---------------------------------------------------------------------------
# Pass 6: Peephole Optimization
# ---------------------------------------------------------------------------

def peephole(code):
    """Pattern-based local optimizations."""
    changed = False
    new_code = []

    for instr in code:
        # NOT NOT -> remove both
        if (new_code and new_code[-1][0] == "NOT" and instr[0] == "NOT"):
            new_code.pop()
            changed = True
            continue

        # NEG NEG -> remove both
        if (new_code and new_code[-1][0] == "NEG" and instr[0] == "NEG"):
            new_code.pop()
            changed = True
            continue

        # PUSH_INT v, POP -> remove both
        if (new_code and new_code[-1][0] == "PUSH_INT" and instr[0] == "POP"):
            new_code.pop()
            changed = True
            continue

        # LOAD x, POP -> remove both (LOAD has no side effects)
        if (new_code and new_code[-1][0] == "LOAD" and instr[0] == "POP"):
            new_code.pop()
            changed = True
            continue

        new_code.append(list(instr))

    return new_code, changed


# ---------------------------------------------------------------------------
# Main optimizer pipeline
# ---------------------------------------------------------------------------

def optimize_code(code):
    """Apply all optimization passes iteratively until fixed point."""
    # Convert to label-based representation
    code = add_labels(code)

    max_iterations = 50
    for _ in range(max_iterations):
        any_changed = False

        code, changed = constant_fold(code)
        any_changed = any_changed or changed

        code, changed = constant_propagate(code)
        any_changed = any_changed or changed

        code, changed = constant_fold(code)
        any_changed = any_changed or changed

        code, changed = dead_store_eliminate(code)
        any_changed = any_changed or changed

        code, changed = unreachable_code_eliminate(code)
        any_changed = any_changed or changed

        code, changed = algebraic_simplify(code)
        any_changed = any_changed or changed

        code, changed = peephole(code)
        any_changed = any_changed or changed

        if not any_changed:
            break

    # Convert back to absolute indices
    code = remove_labels(code)
    return code


def optimize(bytecode):
    """Optimize a full bytecode program (main + all functions)."""
    result = copy.deepcopy(bytecode)

    result["main"] = optimize_code(result["main"])

    for func_name in result.get("functions", {}):
        func = result["functions"][func_name]
        func["code"] = optimize_code(func["code"])

    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 optimizer.py <input.json> <output.json>",
              file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        bytecode = json.load(f)

    optimized = optimize(bytecode)

    with open(sys.argv[2], "w") as f:
        json.dump(optimized, f, indent=2)
