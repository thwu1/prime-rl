
"""Tests for the Decaf compiler pipeline: parser, optimizer, and CFG visualizer."""

import subprocess
import sys
import os
import re
import textwrap

sys.path.insert(0, "/app")
from tac_parser import parse, emit, literal_value, is_literal


def run_optimizer(tac_text: str) -> str:
    """Run the optimizer on the given TAC and return optimized output."""
    result = subprocess.run(
        [sys.executable, "/app/main.py"],
        input=tac_text, capture_output=True, text=True, timeout=30, cwd="/app"
    )
    assert result.returncode == 0, f"Optimizer failed: {result.stderr}"
    return result.stdout


def interpret_tac(tac_text: str) -> list:
    """Simple TAC interpreter that returns list of PRINT outputs and RETURN values."""
    functions = parse(tac_text)
    outputs = []

    def run_func(func, args=None):
        env = {}
        if args and func.params:
            for p, a in zip(func.params, args):
                env[p] = a

        func_map = {f.name: f for f in functions}
        body = [i for i in func.body if i.kind not in ("func_start", "func_end", "param")]
        labels = {}
        for idx, instr in enumerate(body):
            if instr.kind == "label":
                labels[instr.label] = idx

        pc = 0
        max_steps = 10000
        steps = 0
        while pc < len(body) and steps < max_steps:
            steps += 1
            instr = body[pc]

            def resolve(v):
                if v is None:
                    return 0
                if is_literal(v):
                    return literal_value(v)
                return env.get(v, 0)

            if instr.kind == "const_load":
                env[instr.dst] = literal_value(instr.src1)
            elif instr.kind == "copy":
                env[instr.dst] = resolve(instr.src1)
            elif instr.kind == "assign_binop":
                a = resolve(instr.src1)
                b = resolve(instr.src2)
                op = instr.op
                if op == "+": env[instr.dst] = a + b
                elif op == "-": env[instr.dst] = a - b
                elif op == "*": env[instr.dst] = a * b
                elif op == "/": env[instr.dst] = a // b if b != 0 else 0
                elif op == "%": env[instr.dst] = a % b if b != 0 else 0
                elif op == "==": env[instr.dst] = 1 if a == b else 0
                elif op == "!=": env[instr.dst] = 1 if a != b else 0
                elif op == "<": env[instr.dst] = 1 if a < b else 0
                elif op == ">": env[instr.dst] = 1 if a > b else 0
                elif op == "<=": env[instr.dst] = 1 if a <= b else 0
                elif op == ">=": env[instr.dst] = 1 if a >= b else 0
                elif op == "&&": env[instr.dst] = 1 if (a and b) else 0
                elif op == "||": env[instr.dst] = 1 if (a or b) else 0
            elif instr.kind == "assign_unop":
                a = resolve(instr.src1)
                if instr.op == "-": env[instr.dst] = -a
                elif instr.op == "!": env[instr.dst] = 1 if not a else 0
            elif instr.kind == "call":
                if instr.func_name in func_map:
                    call_args = [resolve(x) for x in instr.call_args]
                    ret = run_func(func_map[instr.func_name], call_args)
                    env[instr.dst] = ret if ret is not None else 0
                else:
                    env[instr.dst] = 0
            elif instr.kind == "print":
                val = resolve(instr.src1)
                outputs.append(val)
            elif instr.kind == "goto":
                if instr.label in labels:
                    pc = labels[instr.label]
                    continue
            elif instr.kind == "if_goto":
                if resolve(instr.src1):
                    if instr.label in labels:
                        pc = labels[instr.label]
                        continue
            elif instr.kind == "iffalse_goto":
                if not resolve(instr.src1):
                    if instr.label in labels:
                        pc = labels[instr.label]
                        continue
            elif instr.kind == "return_val":
                return resolve(instr.src1)
            elif instr.kind == "return_void":
                return None
            elif instr.kind == "label":
                pass
            pc += 1
        return None

    for func in functions:
        if func.name == "main":
            run_func(func)
            break

    return outputs


def count_instructions(tac_text: str, kind=None) -> int:
    """Count instructions in TAC text, optionally filtered by kind."""
    funcs = parse(tac_text)
    count = 0
    for f in funcs:
        for i in f.body:
            if i.kind in ("func_start", "func_end"):
                continue
            if kind is None or i.kind == kind:
                count += 1
    return count


def run_parser(dcf_path: str) -> str:
    """Run the decaf2tac parser on a .dcf file and return TAC output."""
    with open(dcf_path) as f:
        source = f.read()
    result = subprocess.run(
        ["/app/decaf2tac"],
        input=source, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"Parser failed on {dcf_path}: {result.stderr}"
    return result.stdout


# ============================================================
# Parser Tests — flex/bison build and correctness
# ============================================================

def test_parser_binary_exists():
    """The decaf2tac parser binary must be built."""
    assert os.path.isfile("/app/decaf2tac"), \
        "decaf2tac binary not found — run 'make' in /app/ to build the parser"


def test_parser_simple_program():
    """Parser produces valid TAC for simple.dcf that evaluates correctly."""
    tac = run_parser("/app/sample_programs/simple.dcf")
    # Must be parseable by Python TAC parser
    funcs = parse(tac)
    assert len(funcs) >= 1, "No functions parsed"
    assert any(f.name == "main" for f in funcs), "No main function found"
    # Interpret and verify output
    outputs = interpret_tac(tac)
    assert outputs == [30], f"simple.dcf: expected [30], got {outputs}"


def test_parser_precedence():
    """Parser correctly handles operator precedence and associativity."""
    tac = run_parser("/app/sample_programs/precedence.dcf")
    outputs = interpret_tac(tac)
    # a = 10 - 3 - 2 = 5 (left-assoc), b = 10 - 3 + 2 = 9, c = 2 + 3*4 = 14, d = (2+3)*4 = 20
    assert outputs == [5, 9, 14, 20], \
        f"precedence.dcf: expected [5, 9, 14, 20], got {outputs}"


def test_parser_control_flow():
    """Parser correctly handles while loops and if/else."""
    tac = run_parser("/app/sample_programs/control.dcf")
    outputs = interpret_tac(tac)
    # while prints total=10, then if prints 1 (since 10==10)
    assert outputs == [10, 1], \
        f"control.dcf: expected [10, 1], got {outputs}"


# ============================================================
# Test 1: Constant Propagation and Folding
# ============================================================

CONST_PROP_INPUT = textwrap.dedent("""\
    FUNC main:
      a = 10
      b = 20
      c = a + b
      d = c * 2
      e = d - 5
      PRINT e
      f = a == 10
      IF f GOTO taken
      PRINT 999
      LABEL taken
      PRINT 42
      RETURN
    END FUNC
""")

def test_constant_propagation_correctness():
    """Optimized code must produce same outputs as original."""
    original_out = interpret_tac(CONST_PROP_INPUT)
    optimized = run_optimizer(CONST_PROP_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out, f"Semantic mismatch: {original_out} vs {optimized_out}"


def test_constant_folding_reduces_code():
    """After folding, there should be no 'a + b' style computations on constants."""
    optimized = run_optimizer(CONST_PROP_INPUT)
    funcs = parse(optimized)
    for f in funcs:
        for i in f.body:
            if i.kind == "assign_binop":
                if is_literal(i.src1) and is_literal(i.src2):
                    assert False, f"Unfold constant expr: {i.src1} {i.op} {i.src2}"


def test_constant_branch_simplified():
    """Branch on a known-true constant should be simplified to GOTO or removed."""
    optimized = run_optimizer(CONST_PROP_INPUT)
    optimized_out = interpret_tac(optimized)
    assert 999 not in optimized_out


# ============================================================
# Test 2: Dead Code Elimination
# ============================================================

DCE_INPUT = textwrap.dedent("""\
    FUNC main:
      a = 5
      b = 10
      c = a + b
      d = 100
      e = d * d
      f = c + 1
      PRINT f
      RETURN
    END FUNC
""")

def test_dce_correctness():
    original_out = interpret_tac(DCE_INPUT)
    optimized = run_optimizer(DCE_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out


def test_dce_removes_dead_assignments():
    """Variables d and e are never used in any live path — must be removed."""
    optimized = run_optimizer(DCE_INPUT)
    funcs = parse(optimized)
    all_dsts = set()
    for f in funcs:
        for i in f.body:
            if i.dst:
                all_dsts.add(i.dst)
    assert "d" not in all_dsts, "Dead variable 'd' not eliminated"
    assert "e" not in all_dsts, "Dead variable 'e' not eliminated"


# ============================================================
# Test 3: Common Subexpression Elimination
# ============================================================

CSE_INPUT = textwrap.dedent("""\
    FUNC main:
      PARAM x
      PARAM y
      a = x + y
      PRINT a
      b = x + y
      PRINT b
      c = x + y
      PRINT c
      RETURN
    END FUNC
    FUNC driver:
      r = CALL main 3 7
      RETURN
    END FUNC
""")

def test_cse_correctness():
    original_out = interpret_tac(CSE_INPUT)
    optimized = run_optimizer(CSE_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out


def test_cse_eliminates_redundant_computations():
    """x+y computed 3 times — after CSE only 1 addition should remain."""
    optimized = run_optimizer(CSE_INPUT)
    funcs = parse(optimized)
    add_count = 0
    for f in funcs:
        if f.name != "main":
            continue
        for i in f.body:
            if i.kind == "assign_binop" and i.op == "+":
                add_count += 1
    assert add_count <= 1, f"Expected at most 1 addition after CSE, got {add_count}"


# ============================================================
# Test 4: Unreachable Code Elimination
# ============================================================

UNREACH_INPUT = textwrap.dedent("""\
    FUNC main:
      a = 1
      GOTO skip
      LABEL dead
      b = 999
      PRINT b
      LABEL skip
      PRINT a
      RETURN
    END FUNC
""")

def test_unreachable_code_correctness():
    original_out = interpret_tac(UNREACH_INPUT)
    optimized = run_optimizer(UNREACH_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out


def test_unreachable_code_removed():
    """The 'dead' block printing 999 is unreachable and should be removed."""
    optimized = run_optimizer(UNREACH_INPUT)
    assert "999" not in optimized, "Unreachable code with '999' not removed"


# ============================================================
# Test 5: Combined — loop with invariant and dead code
# ============================================================

LOOP_INPUT = textwrap.dedent("""\
    FUNC main:
      i = 0
      limit = 5
      total = 0
      dead_var = 123
      LABEL loop_top
      cond = i < limit
      IFFALSE cond GOTO loop_end
      total = total + i
      unused = i * i
      i = i + 1
      GOTO loop_top
      LABEL loop_end
      PRINT total
      RETURN
    END FUNC
""")

def test_loop_correctness():
    original_out = interpret_tac(LOOP_INPUT)
    optimized = run_optimizer(LOOP_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out, f"Loop semantic mismatch: {original_out} vs {optimized_out}"


def test_loop_dead_code_removed():
    """dead_var and unused should be eliminated."""
    optimized = run_optimizer(LOOP_INPUT)
    funcs = parse(optimized)
    all_dsts = set()
    for f in funcs:
        for i in f.body:
            if i.dst:
                all_dsts.add(i.dst)
    assert "dead_var" not in all_dsts, "dead_var not eliminated"
    assert "unused" not in all_dsts, "unused not eliminated"


# ============================================================
# Test 6: Nested constant propagation through copies
# ============================================================

COPY_PROP_INPUT = textwrap.dedent("""\
    FUNC main:
      a = 7
      b = a
      c = b
      d = c
      e = d + 3
      PRINT e
      RETURN
    END FUNC
""")

def test_copy_prop_correctness():
    original_out = interpret_tac(COPY_PROP_INPUT)
    optimized = run_optimizer(COPY_PROP_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out


def test_copy_chain_folded():
    """a=7, b=a, c=b, d=c, e=d+3 should fold to e=10 (or directly PRINT 10)."""
    optimized = run_optimizer(COPY_PROP_INPUT)
    funcs = parse(optimized)
    for f in funcs:
        for i in f.body:
            if i.kind == "assign_binop":
                assert False, f"Binop should be folded away: {_emit_instr_summary(i)}"


def _emit_instr_summary(i):
    if i.kind == "assign_binop":
        return f"{i.dst} = {i.src1} {i.op} {i.src2}"
    return i.kind


# ============================================================
# Test 7: Side effects must be preserved
# ============================================================

SIDE_EFFECT_INPUT = textwrap.dedent("""\
    FUNC side_effect_fn:
      PARAM x
      PRINT x
      RETURN x
    END FUNC
    FUNC main:
      a = CALL side_effect_fn 42
      b = a + 1
      PRINT b
      RETURN
    END FUNC
""")

def test_side_effects_preserved():
    """CALL with side effects must not be removed even if result is used simply."""
    original_out = interpret_tac(SIDE_EFFECT_INPUT)
    optimized = run_optimizer(SIDE_EFFECT_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out


def test_call_not_removed():
    """The CALL instruction must remain — it has side effects."""
    optimized = run_optimizer(SIDE_EFFECT_INPUT)
    assert "CALL" in optimized, "CALL instruction was incorrectly removed"


# ============================================================
# Test 8: Complex — diamond CFG with constant conditions
# ============================================================

DIAMOND_INPUT = textwrap.dedent("""\
    FUNC main:
      x = 1
      cond = x == 1
      IF cond GOTO then_branch
      GOTO else_branch
      LABEL then_branch
      result = 100
      GOTO merge
      LABEL else_branch
      result = 200
      GOTO merge
      LABEL merge
      PRINT result
      RETURN
    END FUNC
""")

def test_diamond_correctness():
    original_out = interpret_tac(DIAMOND_INPUT)
    optimized = run_optimizer(DIAMOND_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out


def test_diamond_dead_branch_removed():
    """Since x==1 is always true, else_branch (result=200) should be unreachable."""
    optimized = run_optimizer(DIAMOND_INPUT)
    assert "200" not in optimized, "Dead else_branch with '200' not removed"


# ============================================================
# Test 9: Constant folding with all arithmetic operators
# ============================================================

ARITH_INPUT = textwrap.dedent("""\
    FUNC main:
      a = 100
      b = 7
      c = a + b
      PRINT c
      d = a - b
      PRINT d
      e = a * b
      PRINT e
      f = a / b
      PRINT f
      g = a % b
      PRINT g
      h = a == b
      PRINT h
      i = a != b
      PRINT i
      j = a < b
      PRINT j
      k = a > b
      PRINT k
      RETURN
    END FUNC
""")

def test_arith_folding_correctness():
    original_out = interpret_tac(ARITH_INPUT)
    optimized = run_optimizer(ARITH_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out, f"Arith mismatch: {original_out} vs {optimized_out}"


def test_arith_all_folded():
    """All arithmetic on constants should be folded — no binops remain."""
    optimized = run_optimizer(ARITH_INPUT)
    funcs = parse(optimized)
    for f in funcs:
        for i in f.body:
            if i.kind == "assign_binop":
                assert False, f"Unfolded binop remains: {i.dst} = {i.src1} {i.op} {i.src2}"


# ============================================================
# Test 10: CSE invalidated by redefinition
# ============================================================

CSE_REDEF_INPUT = textwrap.dedent("""\
    FUNC main:
      PARAM x
      PARAM y
      a = x + y
      PRINT a
      x = 99
      b = x + y
      PRINT b
      RETURN
    END FUNC
    FUNC driver:
      r = CALL main 3 7
      RETURN
    END FUNC
""")

def test_cse_redef_correctness():
    original_out = interpret_tac(CSE_REDEF_INPUT)
    optimized = run_optimizer(CSE_REDEF_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out, f"CSE redef mismatch: {original_out} vs {optimized_out}"


def test_cse_not_applied_after_redef():
    """After x is redefined, x+y is a different expression — CSE must not merge them."""
    optimized = run_optimizer(CSE_REDEF_INPUT)
    funcs = parse(optimized)
    add_count = 0
    for f in funcs:
        if f.name != "main":
            continue
        for i in f.body:
            if i.kind == "assign_binop" and i.op == "+":
                add_count += 1
    assert add_count >= 2, f"CSE incorrectly merged expressions after redefinition (adds={add_count})"


# ============================================================
# Test 11: Multiple function optimization independence
# ============================================================

MULTI_FUNC_INPUT = textwrap.dedent("""\
    FUNC foo:
      a = 3
      b = 4
      c = a + b
      dead = 999
      PRINT c
      RETURN c
    END FUNC
    FUNC main:
      x = 10
      y = 20
      z = x + y
      dead2 = 888
      PRINT z
      RETURN
    END FUNC
""")

def test_multi_func_correctness():
    original_out = interpret_tac(MULTI_FUNC_INPUT)
    optimized = run_optimizer(MULTI_FUNC_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out


def test_multi_func_dead_removed():
    """Dead variables in both functions should be eliminated."""
    optimized = run_optimizer(MULTI_FUNC_INPUT)
    funcs = parse(optimized)
    all_dsts = set()
    for f in funcs:
        for i in f.body:
            if i.dst:
                all_dsts.add(i.dst)
    assert "dead" not in all_dsts, "'dead' not eliminated in foo"
    assert "dead2" not in all_dsts, "'dead2' not eliminated in main"


# ============================================================
# Test 12: Unary constant folding
# ============================================================

UNARY_INPUT = textwrap.dedent("""\
    FUNC main:
      a = 42
      b = - a
      PRINT b
      c = 0
      d = ! c
      PRINT d
      RETURN
    END FUNC
""")

def test_unary_folding_correctness():
    original_out = interpret_tac(UNARY_INPUT)
    optimized = run_optimizer(UNARY_INPUT)
    optimized_out = interpret_tac(optimized)
    assert original_out == optimized_out, f"Unary mismatch: {original_out} vs {optimized_out}"


def test_unary_folded():
    """Unary ops on constants should be folded."""
    optimized = run_optimizer(UNARY_INPUT)
    funcs = parse(optimized)
    for f in funcs:
        for i in f.body:
            if i.kind == "assign_unop":
                assert False, f"Unfolded unary op: {i.op} {i.src1}"


# ============================================================
# Graphviz DOT Output Tests
# ============================================================

DOT_TEST_INPUT = textwrap.dedent("""\
    FUNC main:
      a = 1
      IF a GOTO yes
      GOTO no
      LABEL yes
      PRINT 1
      GOTO done
      LABEL no
      PRINT 0
      LABEL done
      RETURN
    END FUNC
""")

def test_dot_output_valid():
    """cfg_to_dot must produce output that the dot command accepts."""
    result = subprocess.run(
        [sys.executable, "/app/main.py", "--dot", "/tmp/test_dots"],
        input=DOT_TEST_INPUT, capture_output=True, text=True, timeout=30, cwd="/app"
    )
    assert result.returncode == 0, f"main.py --dot failed: {result.stderr}"
    dot_file = "/tmp/test_dots/main.dot"
    assert os.path.isfile(dot_file), f"DOT file not generated: {dot_file}"

    # Validate with dot
    dot_result = subprocess.run(
        ["dot", "-Tsvg", dot_file],
        capture_output=True, text=True, timeout=10
    )
    assert dot_result.returncode == 0, \
        f"dot command failed on {dot_file}: {dot_result.stderr}"


def test_dot_output_structure():
    """DOT output must have nodes for basic blocks and edges for control flow."""
    result = subprocess.run(
        [sys.executable, "/app/main.py", "--dot", "/tmp/test_dots2"],
        input=DOT_TEST_INPUT, capture_output=True, text=True, timeout=30, cwd="/app"
    )
    assert result.returncode == 0
    with open("/tmp/test_dots2/main.dot") as f:
        dot_content = f.read()

    # Must be a digraph
    assert "digraph" in dot_content, "DOT output must be a digraph"
    # Must have at least 2 nodes (basic blocks)
    node_matches = re.findall(r'B\d+\s*\[', dot_content)
    assert len(node_matches) >= 2, \
        f"Expected at least 2 block nodes, found {len(node_matches)}"
    # Must have at least 1 edge
    edge_matches = re.findall(r'B\d+\s*->\s*B\d+', dot_content)
    assert len(edge_matches) >= 1, \
        f"Expected at least 1 edge, found {len(edge_matches)}"


# ============================================================
# End-to-End Pipeline Tests
# ============================================================

def test_end_to_end_simple():
    """Full pipeline: parse simple.dcf, optimize, verify output."""
    tac = run_parser("/app/sample_programs/simple.dcf")
    optimized = run_optimizer(tac)
    outputs = interpret_tac(optimized)
    assert outputs == [30], f"E2E simple: expected [30], got {outputs}"


def test_end_to_end_control():
    """Full pipeline: parse control.dcf, optimize, verify output."""
    tac = run_parser("/app/sample_programs/control.dcf")
    optimized = run_optimizer(tac)
    outputs = interpret_tac(optimized)
    assert outputs == [10, 1], f"E2E control: expected [10, 1], got {outputs}"


def test_end_to_end_with_dot():
    """Full pipeline including DOT generation from parsed source."""
    tac = run_parser("/app/sample_programs/control.dcf")
    result = subprocess.run(
        [sys.executable, "/app/main.py", "--dot", "/tmp/e2e_dots"],
        input=tac, capture_output=True, text=True, timeout=30, cwd="/app"
    )
    assert result.returncode == 0, f"E2E with dot failed: {result.stderr}"
    assert os.path.isfile("/tmp/e2e_dots/main.dot"), "DOT file not generated in E2E"
    # Validate DOT
    dot_result = subprocess.run(
        ["dot", "-Tsvg", "/tmp/e2e_dots/main.dot"],
        capture_output=True, timeout=10
    )
    assert dot_result.returncode == 0, "dot validation failed in E2E"
