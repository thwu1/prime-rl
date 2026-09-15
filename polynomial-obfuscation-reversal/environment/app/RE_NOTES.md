# Reverse Engineering Notes — libseat.so

## File info
- ELF 64-bit LSB shared object, x86-64
- Stripped (no .symtab or debug sections)
- One exported function: `seat_transform` (visible via .dynsym)

## Constant pool
Found 7 contiguous 64-bit values in .rodata (56 bytes total, little-endian):
```
A5A5A5A5A5A5A5A5
BADCAFE0DEADBEEF
1337FACE8BADF00D
FEEDFACEDEADC0DE
3C3C3C3C3C3C3C3C
DEADBEEFCAFEBABE
6969696969696969
```

These are loaded at various points during execution. A second small
constant is loaded inside the inner loop routine — exact value needs
confirmation from the disassembly.

## Structure of seat_transform
The function has a sequential structure:
1. Load input argument
2. Combine with a pool constant (short instruction sequence)
3. Enter a complex loop subroutine
4. Combine with another pool constant
5. Repeat the loop+combine pattern twice more
6. Final combine with a pool constant
7. Return

Total: 4 "combine" operations interleaved with 3 "loop" operations

## Loop subroutine analysis
- Fixed iteration count (need to verify from loop counter setup)
- Uses: shift left, test bit, conditional XOR, shift right
- References a small constant for conditional XOR (reduction?)
- Accumulates result via XOR
- Structure is consistent with polynomial multiplication in GF(2^n)
  but the specific polynomial and field size need verification

## Open questions
- What is the exact reduction constant loaded in the inner loop?
- Precise iteration count of the inner loop
- Exact mapping: which pool indices go to which operation stage
- Whether the "combine" operations are plain XOR or something more complex
- At what bit position is the carry/overflow tested before reduction
