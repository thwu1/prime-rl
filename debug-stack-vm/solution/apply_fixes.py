#!/usr/bin/env python3
"""Apply fixes for all 6 bugs in the MiniStack-16 toolchain.

Assembler bugs (2):
  1. Negative PUSH values masked with 0xFF instead of 0xFFFF
  2. Branch/jump offsets computed relative to instruction start instead of next instruction

Emulator bugs (4):
  3. SHR performs logical shift instead of arithmetic (uint16_t cast)
  4. LT performs unsigned comparison instead of signed (uint16_t casts)
  5. OVER pushes top-of-stack instead of second element (pushes a instead of b)
  6. MOD performs unsigned modulo instead of signed (uint16_t casts)
"""


def fix_assembler():
    path = "/app/assembler.py"
    with open(path, "r") as f:
        code = f.read()

    # Bug 1: Negative PUSH values masked with 0xFF instead of 0xFFFF
    code = code.replace(
        "val = val & 0xFF\n            else:",
        "val = val & 0xFFFF\n            else:",
    )

    # Bug 2: Branch offset uses target_addr - addr instead of
    #         target_addr - (addr + 3)
    code = code.replace(
        "offset = target_addr - addr",
        "offset = target_addr - (addr + 3)",
    )

    with open(path, "w") as f:
        f.write(code)
    print("Fixed assembler.py (2 bugs)")


def fix_emulator():
    path = "/app/emulator.c"
    with open(path, "r") as f:
        code = f.read()

    # Bug 3: SHR performs logical shift (uint16_t cast) instead of arithmetic.
    code = code.replace(
        "(int16_t)((uint16_t)b >> (a & 0xF))",
        "(int16_t)(b >> (a & 0xF))",
        1,
    )

    # Bug 4: LT performs unsigned comparison instead of signed.
    code = code.replace(
        "(uint16_t)b < (uint16_t)a ? 1 : 0",
        "b < a ? 1 : 0",
    )

    # Bug 5: OVER pushes a (top) instead of b (second element).
    # The buggy line has two consecutive stack_push(a) calls.
    code = code.replace(
        "stack_push(a);\n            stack_push(a);  /* copies top-of-stack instead of second element */",
        "stack_push(a);\n            stack_push(b);",
    )

    # Bug 6: MOD performs unsigned modulo instead of signed.
    code = code.replace(
        "(int16_t)((uint16_t)b % (uint16_t)a)",
        "b % a",
    )

    with open(path, "w") as f:
        f.write(code)
    print("Fixed emulator.c (4 bugs)")


if __name__ == "__main__":
    fix_assembler()
    fix_emulator()
