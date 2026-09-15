A DWARF `.debug_frame` CFI decoder at `/app/dwarf_cfi.c` reads raw `.debug_frame` section bytes and outputs decoded CIE and FDE entries with register rule tables at each code location — the unwind information debuggers use to walk the call stack.

The decoder compiles but produces incorrect output for various inputs. Make it fully conform to the DWARF debugging information format specification for `.debug_frame` sections.

**Interface:**

```
./dwarf_cfi <debug_frame_file> [address_size]
```

- `debug_frame_file`: path to raw `.debug_frame` section bytes
- `address_size`: target address size in bytes (default: 8)

**Output format:**

```
CIE @0x<offset>: v=<ver> ca=<code_align> da=<data_align> ret=<ret_reg> aug="<aug>"
  [initial] cfa=r<N>+<off> {r<M>=[cfa+<off>] ...}
FDE @0x<offset>: pc=[0x<lo>,0x<hi>) cie=@0x<cie_off>
  [0x<addr>] cfa=r<N>+<off> {r<M>=[cfa+<off>] ...}
```

Register rules: `r<N>=[cfa+<off>]` (offset), `r<N>=val(cfa+<off>)` (val_offset), `r<N>=same` (same_value), `r<N>=r<M>` (register), `r<N>=expr` (expression), `r<N>=val_expr` (val_expression).

**Required capabilities:**

- CIE versions 1 and 4
- 32-bit and 64-bit DWARF format (DWARF Section 7.4)
- All standard DW_CFA_* opcodes defined in DWARF Sections 6.4.2.1 through 6.4.2.5, including both unsigned-factored and signed-factored variants

**Build:** `make -C /app dwarf_cfi`

**Success criteria:** `make -C /app dwarf_cfi` compiles without errors and all verification tests pass.
