
"""
Pseudo-x86 test programs for the register allocator.

Instruction format:
    (opcode, arg1, arg2, ...)

Argument types:
    ("imm", value)          — immediate integer
    ("var", name)           — pseudo-register (variable to be allocated)
    ("reg", name)           — physical register (pre-colored)
    ("deref", reg, offset)  — memory at [reg + offset]

Jump targets and function names are plain strings.
callq format: ("callq", func_name, arity)

Each program is a dict:
    "blocks":  dict of label -> list of instructions
    "expected_rax": expected value in %rax upon reaching 'conclusion'
    "expected_output": list of ints printed by print_int calls
"""

PROGRAMS = {
    # ------------------------------------------------------------------
    # 1. Straight-line arithmetic, 6 variables
    #    From Siek Ch.2 example: v=1, w=42, x=v+7=8, y=x=8, z=x+w=50,
    #    t=-y=-8, result = z + t = 42
    # ------------------------------------------------------------------
    "simple_arith": {
        "blocks": {
            "start": [
                ("movq", ("imm", 1), ("var", "v")),
                ("movq", ("imm", 42), ("var", "w")),
                ("movq", ("var", "v"), ("var", "x")),
                ("addq", ("imm", 7), ("var", "x")),
                ("movq", ("var", "x"), ("var", "y")),
                ("movq", ("var", "x"), ("var", "z")),
                ("addq", ("var", "w"), ("var", "z")),
                ("movq", ("var", "y"), ("var", "t")),
                ("negq", ("var", "t")),
                ("movq", ("var", "z"), ("reg", "rax")),
                ("addq", ("var", "t"), ("reg", "rax")),
                ("jmp", "conclusion"),
            ],
        },
        "expected_rax": 42,
        "expected_output": [],
    },

    # ------------------------------------------------------------------
    # 2. Conditional branch: a=3, b=7. Since 3 < 5, take then-branch:
    #    a = a + b = 10
    # ------------------------------------------------------------------
    "branches": {
        "blocks": {
            "start": [
                ("movq", ("imm", 3), ("var", "a")),
                ("movq", ("imm", 7), ("var", "b")),
                ("cmpq", ("imm", 5), ("var", "a")),
                ("jl", "then_branch"),
                ("jmp", "else_branch"),
            ],
            "then_branch": [
                ("addq", ("var", "b"), ("var", "a")),
                ("movq", ("var", "a"), ("reg", "rax")),
                ("jmp", "conclusion"),
            ],
            "else_branch": [
                ("subq", ("var", "b"), ("var", "a")),
                ("movq", ("var", "a"), ("reg", "rax")),
                ("jmp", "conclusion"),
            ],
        },
        "expected_rax": 10,
        "expected_output": [],
    },

    # ------------------------------------------------------------------
    # 3. While loop: sum = 1+2+...+10 = 55
    #    Requires fixed-point liveness analysis across back edge.
    # ------------------------------------------------------------------
    "loop": {
        "blocks": {
            "start": [
                ("movq", ("imm", 0), ("var", "sum")),
                ("movq", ("imm", 1), ("var", "i")),
                ("jmp", "header"),
            ],
            "header": [
                ("cmpq", ("imm", 11), ("var", "i")),
                ("jl", "body"),
                ("jmp", "exit"),
            ],
            "body": [
                ("addq", ("var", "i"), ("var", "sum")),
                ("addq", ("imm", 1), ("var", "i")),
                ("jmp", "header"),
            ],
            "exit": [
                ("movq", ("var", "sum"), ("reg", "rax")),
                ("jmp", "conclusion"),
            ],
        },
        "expected_rax": 55,
        "expected_output": [],
    },

    # ------------------------------------------------------------------
    # 4. Fibonacci: compute fib(12) = 144 iteratively
    #    4 variables (a, b, tmp, n) with move chains;
    #    move biasing helps reduce trivial moves.
    # ------------------------------------------------------------------
    "fibonacci": {
        "blocks": {
            "start": [
                ("movq", ("imm", 0), ("var", "a")),
                ("movq", ("imm", 1), ("var", "b")),
                ("movq", ("imm", 2), ("var", "n")),
                ("jmp", "header"),
            ],
            "header": [
                ("cmpq", ("imm", 13), ("var", "n")),
                ("jl", "body"),
                ("jmp", "exit"),
            ],
            "body": [
                ("movq", ("var", "a"), ("var", "tmp")),
                ("movq", ("var", "b"), ("var", "a")),
                ("addq", ("var", "tmp"), ("var", "b")),
                ("addq", ("imm", 1), ("var", "n")),
                ("jmp", "header"),
            ],
            "exit": [
                ("movq", ("var", "b"), ("reg", "rax")),
                ("jmp", "conclusion"),
            ],
        },
        "expected_rax": 144,
        "expected_output": [],
    },

    # ------------------------------------------------------------------
    # 5. Many variables: 15 vars all live simultaneously
    #    With 12 allocatable registers, forces 3+ spills.
    #    sum = 1+2+...+15 = 120
    # ------------------------------------------------------------------
    "many_vars": {
        "blocks": {
            "start": [
                ("movq", ("imm", 1), ("var", "a")),
                ("movq", ("imm", 2), ("var", "b")),
                ("movq", ("imm", 3), ("var", "c")),
                ("movq", ("imm", 4), ("var", "d")),
                ("movq", ("imm", 5), ("var", "e")),
                ("movq", ("imm", 6), ("var", "f")),
                ("movq", ("imm", 7), ("var", "g")),
                ("movq", ("imm", 8), ("var", "h")),
                ("movq", ("imm", 9), ("var", "j")),
                ("movq", ("imm", 10), ("var", "k")),
                ("movq", ("imm", 11), ("var", "l")),
                ("movq", ("imm", 12), ("var", "m")),
                ("movq", ("imm", 13), ("var", "q")),
                ("movq", ("imm", 14), ("var", "o")),
                ("movq", ("imm", 15), ("var", "p")),
                ("movq", ("var", "a"), ("var", "r")),
                ("addq", ("var", "b"), ("var", "r")),
                ("addq", ("var", "c"), ("var", "r")),
                ("addq", ("var", "d"), ("var", "r")),
                ("addq", ("var", "e"), ("var", "r")),
                ("addq", ("var", "f"), ("var", "r")),
                ("addq", ("var", "g"), ("var", "r")),
                ("addq", ("var", "h"), ("var", "r")),
                ("addq", ("var", "j"), ("var", "r")),
                ("addq", ("var", "k"), ("var", "r")),
                ("addq", ("var", "l"), ("var", "r")),
                ("addq", ("var", "m"), ("var", "r")),
                ("addq", ("var", "q"), ("var", "r")),
                ("addq", ("var", "o"), ("var", "r")),
                ("addq", ("var", "p"), ("var", "r")),
                ("movq", ("var", "r"), ("reg", "rax")),
                ("jmp", "conclusion"),
            ],
        },
        "expected_rax": 120,
        "expected_output": [],
    },

    # ------------------------------------------------------------------
    # 6. Nested loops:
    #    total = sum of (i+j) for i=1..4, j=1..4 = 80
    #    Tests fixed-point across nested back edges.
    # ------------------------------------------------------------------
    "nested_loops": {
        "blocks": {
            "start": [
                ("movq", ("imm", 0), ("var", "total")),
                ("movq", ("imm", 1), ("var", "i")),
                ("jmp", "outer_header"),
            ],
            "outer_header": [
                ("cmpq", ("imm", 5), ("var", "i")),
                ("jl", "outer_body"),
                ("jmp", "done"),
            ],
            "outer_body": [
                ("movq", ("imm", 1), ("var", "j")),
                ("jmp", "inner_header"),
            ],
            "inner_header": [
                ("cmpq", ("imm", 5), ("var", "j")),
                ("jl", "inner_body"),
                ("jmp", "inner_done"),
            ],
            "inner_body": [
                ("movq", ("var", "i"), ("var", "tmp")),
                ("addq", ("var", "j"), ("var", "tmp")),
                ("addq", ("var", "tmp"), ("var", "total")),
                ("addq", ("imm", 1), ("var", "j")),
                ("jmp", "inner_header"),
            ],
            "inner_done": [
                ("addq", ("imm", 1), ("var", "i")),
                ("jmp", "outer_header"),
            ],
            "done": [
                ("movq", ("var", "total"), ("reg", "rax")),
                ("jmp", "conclusion"),
            ],
        },
        "expected_rax": 80,
        "expected_output": [],
    },

    # ------------------------------------------------------------------
    # 7. Function calls with caller-saved register handling:
    #    a=1, b=2, b=a+b=3, print(3),
    #    c=10, c=b+c=13, print(13),
    #    c=a+c=14, rax=14
    #    Variables a, b live across calls must be in callee-saved regs.
    # ------------------------------------------------------------------
    "with_calls": {
        "blocks": {
            "start": [
                ("movq", ("imm", 1), ("var", "a")),
                ("movq", ("imm", 2), ("var", "b")),
                ("addq", ("var", "a"), ("var", "b")),
                ("movq", ("var", "b"), ("reg", "rdi")),
                ("callq", "print_int", 1),
                ("movq", ("imm", 10), ("var", "c")),
                ("addq", ("var", "b"), ("var", "c")),
                ("movq", ("var", "c"), ("reg", "rdi")),
                ("callq", "print_int", 1),
                ("addq", ("var", "a"), ("var", "c")),
                ("movq", ("var", "c"), ("reg", "rax")),
                ("jmp", "conclusion"),
            ],
        },
        "expected_rax": 14,
        "expected_output": [3, 13],
    },
}
