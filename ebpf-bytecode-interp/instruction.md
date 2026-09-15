Pre-compiled BPF ELF object files (produced by `clang -target bpf`) are in `/app/programs/`. A brief ISA reference is at `/app/reference/bpf_isa.txt`. Sample programs with hex bytecode and expected outputs are at `/app/samples/sample_programs.json`. Binary analysis tools are available: `llvm-objdump`, `llvm-readelf`, `readelf`, `objdump`, `llvm-objcopy`.

Build three executable tools:

## `/app/bpf_extract <elf_file>`

Extract BPF program bytecode from a compiled BPF ELF object file. Output the raw bytecode as a lowercase hex string to stdout. Exit 0 on success. BPF programs reside in named ELF sections — use the installed binary analysis tools to discover the correct section layout.

## `/app/bpf_analyze <hex_bytecode>`

Perform static control-flow and register analysis on raw BPF bytecode (hex string argument). Output a JSON object to stdout with:

- `instruction_count` (int): number of logical BPF instructions (LD_IMM64 counts as 1, despite occupying 2 slots)
- `basic_blocks` (list[int]): sorted slot indices where basic blocks begin (slot 0 always included; each slot is 8 bytes)
- `edges` (list[[int,int]]): CFG edges as `[from_block_start, to_block_start]` pairs
- `has_back_edges` (bool): true if any CFG edge targets a block at or before the source block index
- `max_stack_depth` (int): maximum byte offset from R10 used in any ST/STX/LDX instruction (e.g., deepest access at `[R10-64]` yields 64; 0 if no stack access)
- `registers_written` (list[int]): sorted register numbers (0-9) written to by any instruction in the program

## `/app/bpf_run <hex_bytecode>`

Execute BPF bytecode (hex string argument) and print the unsigned 64-bit value of R0 at the EXIT instruction as a decimal integer to stdout. Exit 0 on success. Registers R0-R9 start at 0; R10 is the read-only frame pointer for a 512-byte stack.