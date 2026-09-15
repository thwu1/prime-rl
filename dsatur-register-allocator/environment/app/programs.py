"""
Test programs for the register allocator.
Each entry: (name, X86Program-with-Variables, expected_output, inputs).
"""
from ir import Immediate as Im, Register as Reg, Variable as Var
from ir import Instr, Callq, Jump, JumpIf, X86Program


def get_test_programs():
    V = Var
    R = lambda r: Reg(r)
    I = lambda v: Im(v)
    programs = []

    # ── 1. simple_arith ───────────────────────────────────────────────────────
    # v=1  w=42  x=v+7=8  y=x=8  z=x+w=50  t=-y=-8  print(z+t)=42
    programs.append(("simple_arith", X86Program({
        "start": [
            Instr("movq", [I(1),  V("v")]),
            Instr("movq", [I(42), V("w")]),
            Instr("movq", [V("v"), V("x")]),
            Instr("addq", [I(7),  V("x")]),
            Instr("movq", [V("x"), V("y")]),
            Instr("movq", [V("x"), V("z")]),
            Instr("addq", [V("w"), V("z")]),
            Instr("movq", [V("y"), V("t")]),
            Instr("negq", [V("t")]),
            Instr("movq", [V("z"), R("rdi")]),
            Instr("addq", [V("t"), R("rdi")]),
            Callq("print_int", 1),
            Instr("movq", [I(0), R("rax")]),
            Jump("conclusion"),
        ],
        "conclusion": [],
    }), [42], []))

    # ── 2. with_branch ────────────────────────────────────────────────────────
    # if 10 >= 5 then 10-5 else 0  => 5
    programs.append(("with_branch", X86Program({
        "start": [
            Instr("movq", [I(10), V("x")]),
            Instr("movq", [I(5),  V("y")]),
            Instr("cmpq", [V("y"), V("x")]),   # x - y => flags
            JumpIf("l", "less_branch"),
            Jump("ge_branch"),
        ],
        "less_branch": [
            Instr("movq", [I(0), V("result")]),
            Jump("done"),
        ],
        "ge_branch": [
            Instr("movq", [V("x"), V("result")]),
            Instr("subq", [V("y"), V("result")]),
            Jump("done"),
        ],
        "done": [
            Instr("movq", [V("result"), R("rdi")]),
            Callq("print_int", 1),
            Instr("movq", [I(0), R("rax")]),
            Jump("conclusion"),
        ],
        "conclusion": [],
    }), [5], []))

    # ── 3. while_loop ─────────────────────────────────────────────────────────
    # sum = 1+2+…+10 = 55
    programs.append(("while_loop", X86Program({
        "start": [
            Instr("movq", [I(0), V("sum")]),
            Instr("movq", [I(1), V("i")]),
            Jump("loop_test"),
        ],
        "loop_test": [
            Instr("cmpq", [I(11), V("i")]),   # i - 11
            JumpIf("l", "loop_body"),           # i < 11
            Jump("loop_done"),
        ],
        "loop_body": [
            Instr("addq", [V("i"), V("sum")]),
            Instr("addq", [I(1),  V("i")]),
            Jump("loop_test"),
        ],
        "loop_done": [
            Instr("movq", [V("sum"), R("rdi")]),
            Callq("print_int", 1),
            Instr("movq", [I(0), R("rax")]),
            Jump("conclusion"),
        ],
        "conclusion": [],
    }), [55], []))

    # ── 4. high_pressure ──────────────────────────────────────────────────────
    # 13 simultaneously live variables (> 11 registers  =>  spills required)
    # 1+2+…+13 = 91
    programs.append(("high_pressure", X86Program({
        "start": [
            Instr("movq", [I(1),  V("a")]),
            Instr("movq", [I(2),  V("b")]),
            Instr("movq", [I(3),  V("c")]),
            Instr("movq", [I(4),  V("d")]),
            Instr("movq", [I(5),  V("e")]),
            Instr("movq", [I(6),  V("f")]),
            Instr("movq", [I(7),  V("g")]),
            Instr("movq", [I(8),  V("h")]),
            Instr("movq", [I(9),  V("ii")]),
            Instr("movq", [I(10), V("j")]),
            Instr("movq", [I(11), V("k")]),
            Instr("movq", [I(12), V("l")]),
            Instr("movq", [I(13), V("m")]),
            Instr("movq", [V("a"),  V("result")]),
            Instr("addq", [V("b"),  V("result")]),
            Instr("addq", [V("c"),  V("result")]),
            Instr("addq", [V("d"),  V("result")]),
            Instr("addq", [V("e"),  V("result")]),
            Instr("addq", [V("f"),  V("result")]),
            Instr("addq", [V("g"),  V("result")]),
            Instr("addq", [V("h"),  V("result")]),
            Instr("addq", [V("ii"), V("result")]),
            Instr("addq", [V("j"),  V("result")]),
            Instr("addq", [V("k"),  V("result")]),
            Instr("addq", [V("l"),  V("result")]),
            Instr("addq", [V("m"),  V("result")]),
            Instr("movq", [V("result"), R("rdi")]),
            Callq("print_int", 1),
            Instr("movq", [I(0), R("rax")]),
            Jump("conclusion"),
        ],
        "conclusion": [],
    }), [91], []))

    # ── 5. calls_and_live ─────────────────────────────────────────────────────
    # Variable x is live across a call  =>  must be in a callee-saved register.
    # print(42), print(50)
    programs.append(("calls_and_live", X86Program({
        "start": [
            Instr("movq", [I(42), V("x")]),
            Instr("movq", [V("x"), R("rdi")]),
            Callq("print_int", 1),
            Instr("movq", [V("x"), V("y")]),
            Instr("addq", [I(8),  V("y")]),
            Instr("movq", [V("y"), R("rdi")]),
            Callq("print_int", 1),
            Instr("movq", [I(0), R("rax")]),
            Jump("conclusion"),
        ],
        "conclusion": [],
    }), [42, 50], []))

    # ── 6. fibonacci_loop ─────────────────────────────────────────────────────
    # fib(10) = 89 — tests fixed-point liveness across a loop back-edge
    programs.append(("fibonacci_loop", X86Program({
        "start": [
            Instr("movq", [I(1), V("a")]),
            Instr("movq", [I(1), V("b")]),
            Instr("movq", [I(1), V("counter")]),
            Jump("loop_test"),
        ],
        "loop_test": [
            Instr("cmpq", [I(10), V("counter")]),
            JumpIf("l", "loop_body"),
            Jump("loop_done"),
        ],
        "loop_body": [
            Instr("movq", [V("b"), V("temp")]),
            Instr("addq", [V("a"), V("b")]),
            Instr("movq", [V("temp"), V("a")]),
            Instr("addq", [I(1),  V("counter")]),
            Jump("loop_test"),
        ],
        "loop_done": [
            Instr("movq", [V("b"), R("rdi")]),
            Callq("print_int", 1),
            Instr("movq", [I(0), R("rax")]),
            Jump("conclusion"),
        ],
        "conclusion": [],
    }), [89], []))

    # ── 7. nested_loops ───────────────────────────────────────────────────────
    # sum of i*i for i=1..4  =>  1+4+9+16 = 30
    # (inner loop adds i exactly i times to compute i*i)
    programs.append(("nested_loops", X86Program({
        "start": [
            Instr("movq", [I(0), V("total")]),
            Instr("movq", [I(1), V("i")]),
            Jump("outer_test"),
        ],
        "outer_test": [
            Instr("cmpq", [I(5), V("i")]),
            JumpIf("l", "outer_body"),
            Jump("outer_done"),
        ],
        "outer_body": [
            Instr("movq", [I(0), V("partial")]),
            Instr("movq", [I(0), V("j")]),
            Jump("inner_test"),
        ],
        "inner_test": [
            Instr("cmpq", [V("i"), V("j")]),    # j - i
            JumpIf("l", "inner_body"),            # j < i
            Jump("inner_done"),
        ],
        "inner_body": [
            Instr("addq", [V("i"), V("partial")]),
            Instr("addq", [I(1),  V("j")]),
            Jump("inner_test"),
        ],
        "inner_done": [
            Instr("addq", [V("partial"), V("total")]),
            Instr("addq", [I(1), V("i")]),
            Jump("outer_test"),
        ],
        "outer_done": [
            Instr("movq", [V("total"), R("rdi")]),
            Callq("print_int", 1),
            Instr("movq", [I(0), R("rax")]),
            Jump("conclusion"),
        ],
        "conclusion": [],
    }), [30], []))

    return programs
