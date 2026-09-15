"""
Test programs for the register allocator.

Each function returns a Program with virtual registers.  The expected
output (from the emulator) is documented in comments.
"""


from ir import *


# ---------- 1. trivial: straight-line, two adds ----------
# Expected: [30]
def trivial():
    return Program({
        'entry': [
            CONST('v0', 10),
            CONST('v1', 20),
            ADD('v2', 'v0', 'v1'),
            PRINT('v2'),
            RET(),
        ],
    })


# ---------- 2. chain: ops with varying lifetimes ----------
# Expected: [8, 15, -7]
def chain():
    return Program({
        'entry': [
            CONST('v0', 5),
            CONST('v1', 3),
            ADD('v2', 'v0', 'v1'),      # 8
            MUL('v3', 'v0', 'v1'),      # 15
            PRINT('v2'),
            SUB('v4', 'v2', 'v3'),      # -7
            PRINT('v3'),
            PRINT('v4'),
            RET(),
        ],
    })


# ---------- 3. branch: if-then-else (abs difference) ----------
# Expected: [27]
def branch():
    return Program({
        'entry': [
            CONST('v0', 15),
            CONST('v1', 42),
            CMP_LT('v2', 'v0', 'v1'),
            BR('v2', 'less', 'geq'),
        ],
        'less': [
            SUB('v3', 'v1', 'v0'),
            JMP('merge'),
        ],
        'geq': [
            SUB('v3', 'v0', 'v1'),
            JMP('merge'),
        ],
        'merge': [
            PRINT('v3'),
            RET(),
        ],
    })


# ---------- 4. diamond: double diamond CFG ----------
# Expected: [900]
def diamond():
    return Program({
        'entry': [
            CONST('v0', 10),
            CONST('v1', 20),
            CONST('v2', 30),
            CMP_LT('v3', 'v0', 'v1'),   # true
            BR('v3', 'left1', 'right1'),
        ],
        'left1': [
            ADD('v4', 'v0', 'v1'),       # 30
            JMP('mid'),
        ],
        'right1': [
            SUB('v4', 'v0', 'v1'),
            JMP('mid'),
        ],
        'mid': [
            CMP_LT('v5', 'v4', 'v2'),   # 30 < 30 → false
            BR('v5', 'left2', 'right2'),
        ],
        'left2': [
            ADD('v6', 'v4', 'v2'),
            JMP('end'),
        ],
        'right2': [
            MUL('v6', 'v4', 'v2'),      # 900
            JMP('end'),
        ],
        'end': [
            PRINT('v6'),
            RET(),
        ],
    })


# ---------- 5. loop_sum: sum 1..10 (fixpoint liveness) ----------
# Expected: [55]
def loop_sum():
    return Program({
        'entry': [
            CONST('v0', 0),     # sum
            CONST('v1', 1),     # i
            CONST('v2', 11),    # limit
            CONST('v3', 1),     # increment
            JMP('loop'),
        ],
        'loop': [
            CMP_LT('v4', 'v1', 'v2'),
            BR('v4', 'body', 'done'),
        ],
        'body': [
            ADD('v0', 'v0', 'v1'),
            ADD('v1', 'v1', 'v3'),
            JMP('loop'),
        ],
        'done': [
            PRINT('v0'),
            RET(),
        ],
    })


# ---------- 6. fibonacci: 10 Fibonacci numbers ----------
# Expected: [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
def fibonacci():
    return Program({
        'entry': [
            CONST('v0', 0),     # a
            CONST('v1', 1),     # b
            CONST('v2', 0),     # counter
            CONST('v3', 10),    # limit
            CONST('v4', 1),     # const 1
            JMP('loop'),
        ],
        'loop': [
            CMP_LT('v5', 'v2', 'v3'),
            BR('v5', 'body', 'done'),
        ],
        'body': [
            PRINT('v0'),
            ADD('v6', 'v0', 'v1'),    # temp = a + b
            MOV('v0', 'v1'),          # a = b
            MOV('v1', 'v6'),          # b = temp
            ADD('v2', 'v2', 'v4'),    # counter++
            JMP('loop'),
        ],
        'done': [
            RET(),
        ],
    })


# ---------- 7. gcd: Euclidean algorithm ----------
# Expected: [6]
def gcd():
    return Program({
        'entry': [
            CONST('v0', 48),    # a
            CONST('v1', 18),    # b
            JMP('loop'),
        ],
        'loop': [
            CONST('v2', 0),
            CMP_EQ('v3', 'v1', 'v2'),   # b == 0?
            BR('v3', 'done', 'step'),
        ],
        'step': [
            MOD('v4', 'v0', 'v1'),      # a % b
            MOV('v0', 'v1'),             # a = b
            MOV('v1', 'v4'),             # b = remainder
            JMP('loop'),
        ],
        'done': [
            PRINT('v0'),
            RET(),
        ],
    })


# ---------- 8. loop_branch: loop with inner diamond ----------
# Expected: [2, 6, 6, 12, 10]
def loop_branch():
    return Program({
        'entry': [
            CONST('v0', 1),     # k
            CONST('v1', 6),     # limit
            CONST('v2', 2),     # const
            CONST('v3', 3),     # const
            JMP('loop'),
        ],
        'loop': [
            CMP_LT('v4', 'v0', 'v1'),
            BR('v4', 'body', 'done'),
        ],
        'body': [
            MOD('v5', 'v0', 'v2'),
            CONST('v6', 0),
            CMP_EQ('v7', 'v5', 'v6'),
            BR('v7', 'even', 'odd'),
        ],
        'even': [
            MUL('v8', 'v0', 'v3'),
            PRINT('v8'),
            JMP('next'),
        ],
        'odd': [
            MUL('v8', 'v0', 'v2'),
            PRINT('v8'),
            JMP('next'),
        ],
        'next': [
            CONST('v9', 1),
            ADD('v0', 'v0', 'v9'),
            JMP('loop'),
        ],
        'done': [
            RET(),
        ],
    })


# ---------- 9. spill_straight: 8 simultaneous live variables ----------
# Expected: [279]
def spill_straight():
    return Program({
        'entry': [
            CONST('v0', 2),
            CONST('v1', 3),
            CONST('v2', 5),
            CONST('v3', 7),
            CONST('v4', 11),
            CONST('v5', 13),
            CONST('v6', 17),
            CONST('v7', 19),
            MUL('v8', 'v0', 'v4'),     # 2*11=22
            MUL('v9', 'v1', 'v5'),     # 3*13=39
            MUL('v10', 'v2', 'v6'),    # 5*17=85
            MUL('v11', 'v3', 'v7'),    # 7*19=133
            ADD('v12', 'v8', 'v9'),    # 22+39=61
            ADD('v13', 'v10', 'v11'),  # 85+133=218
            ADD('v14', 'v12', 'v13'),  # 61+218=279
            PRINT('v14'),
            RET(),
        ],
    })


# ---------- 10. spill_many: 11 simultaneously live vars ----------
# Expected: [1, 2, 3, 4, 5, 6, 7, 22]
def spill_many():
    return Program({
        'entry': [
            CONST('v0', 1),
            CONST('v1', 2),
            CONST('v2', 3),
            CONST('v3', 4),
            CONST('v4', 5),
            CONST('v5', 6),
            CONST('v6', 7),
            ADD('v7', 'v0', 'v1'),      # 3
            MUL('v8', 'v2', 'v3'),      # 12
            SUB('v9', 'v4', 'v5'),      # -1
            ADD('v10', 'v6', 'v0'),     # 8
            ADD('v11', 'v7', 'v8'),     # 15
            ADD('v12', 'v9', 'v10'),    # 7
            ADD('v13', 'v11', 'v12'),   # 22
            PRINT('v0'),
            PRINT('v1'),
            PRINT('v2'),
            PRINT('v3'),
            PRINT('v4'),
            PRINT('v5'),
            PRINT('v6'),
            PRINT('v13'),
            RET(),
        ],
    })


# ---------- 11. spill_loop: high pressure inside a loop ----------
# Expected: [784, 100, 200, 300]
def spill_loop():
    return Program({
        'entry': [
            CONST('v0', 0),      # total (sum of cubes)
            CONST('v1', 1),      # k
            CONST('v2', 8),      # limit (k < 8, so k = 1..7)
            CONST('v4', 1),      # const for increment
            CONST('v5', 100),    # distractor (live across loop)
            CONST('v6', 200),    # distractor
            CONST('v7', 300),    # distractor
            JMP('loop'),
        ],
        'loop': [
            CMP_LT('v8', 'v1', 'v2'),
            BR('v8', 'body', 'done'),
        ],
        'body': [
            MUL('v9', 'v1', 'v1'),     # k^2
            MUL('v10', 'v9', 'v1'),    # k^3
            ADD('v0', 'v0', 'v10'),    # total += k^3
            ADD('v1', 'v1', 'v4'),     # k++
            JMP('loop'),
        ],
        'done': [
            PRINT('v0'),
            PRINT('v5'),
            PRINT('v6'),
            PRINT('v7'),
            RET(),
        ],
    })


def get_all_programs():
    """Return list of (name, Program) pairs for testing."""
    return [
        ('trivial', trivial()),
        ('chain', chain()),
        ('branch', branch()),
        ('diamond', diamond()),
        ('loop_sum', loop_sum()),
        ('fibonacci', fibonacci()),
        ('gcd', gcd()),
        ('loop_branch', loop_branch()),
        ('spill_straight', spill_straight()),
        ('spill_many', spill_many()),
        ('spill_loop', spill_loop()),
    ]
