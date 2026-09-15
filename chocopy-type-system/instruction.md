A ChocoPy v2.2 compiler produced a RISC-V ELF object file at `/app/compiler_output.o` from a program whose class definitions are at `/app/class_defs.py`. The formal type system specification is at `/app/spec.md`. The cross-architecture toolchain `binutils-riscv64-linux-gnu` is installed — use `riscv64-linux-gnu-objdump`, `riscv64-linux-gnu-nm`, `riscv64-linux-gnu-readelf`, or related tools to analyze the binary artifact.

The file `/app/chocopy_types.py` is a skeleton defining the `ChocoPyTypeSystem` class API; every core type-system method raises `NotImplementedError`. The hierarchy file `/app/hierarchy.json` required by its constructor does not exist.

Produce:

- `/app/hierarchy.json` — the class hierarchy JSON expected by `ChocoPyTypeSystem.__init__()`. Extract prototype type tags, dispatch table layouts, and object sizes from the object file to determine the compiler's class ordering. Built-in classes (`object`, `int`, `bool`, `str`) must precede user-defined classes, whose order must match the type tag sequence encoded in the binary's prototype objects.

- A complete `/app/chocopy_types.py` — implement all 13 stubbed operations (conformance, assignment compatibility, join, method resolution, override validation, all expression typing rules, attribute access, and object layout queries) per the specification. The implementation must correctly handle special types (`<None>`, `<Empty>`), list type invariance, recursive assignment rules, bidirectional join checks, and the full operator typing matrix.