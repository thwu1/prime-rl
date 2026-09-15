Build an eBPF bytecode static analyzer at `/app/ebpf_analyzer.py`. The tool reads raw eBPF program bytecode from binary files in `/app/programs/` with corresponding metadata from `/app/metadata.json`, then writes per-program analysis results to `/app/results/<name>.json`.

Each binary file contains sequentially packed eBPF instructions. Each instruction is 8 bytes in little-endian format: opcode (u8), dst_reg:4|src_reg:4 (u8, dst in low nibble, src in high nibble), offset (signed i16), immediate (signed i32). The `BPF_LD_IMM64` instruction (opcode `0x18`) spans two consecutive 8-byte slots; both slots count as separate instruction indices.

The analyzer must produce for each program a JSON file `/app/results/<name>.json` with:

- `program`: the program name
- `num_instructions`: total instruction count including LD_IMM64 continuation slots
- `cfg`: control flow graph as an adjacency list mapping each instruction index (string key) to a list of successor instruction indices. Sequential instructions flow to the next; `BPF_JMP_JA` (opcode `0x05`) is an unconditional jump to `pc + 1 + offset`; conditional jumps (JEQ, JNE, JGT, JGE with K or X variants) branch to both `pc + 1` (fall-through) and `pc + 1 + offset` (target); `BPF_EXIT` (opcode `0x95`) has no successors; `BPF_CALL` (opcode `0x85`) falls through.
- `findings`: list of detected issues, each with `type` (string) and `instruction` (the index of the offending instruction)

Detect these four verification issue types:

- `null_ptr_deref`: The return value register (R0) from a `bpf_map_lookup_elem` call (helper #1, via opcode `0x85` with imm=1) is used as a base register in a memory load (LDX) without a preceding conditional check comparing R0 to zero.
- `packet_bounds`: In XDP-type programs, packet data obtained by loading from the context pointer (R1 at entry) at offset 0 (`xdp_md->data`) is accessed via a memory load without a prior bounds comparison between a data-derived pointer and the `data_end` pointer (loaded from context offset 4). Track register types through MOV and ADD instructions to identify packet data pointers and detect when they are dereferenced before a bounds check against `data_end`.
- `unreachable_code`: Instructions not reachable from the entry point (instruction index 0) via CFG traversal. Do not flag LD_IMM64 continuation slots as unreachable.
- `stack_out_of_bounds`: Memory load or store through R10 (frame pointer) with an offset below -512.

The `/app/programs/` directory contains 6 binary eBPF programs and `/app/metadata.json` describes their types and map definitions. Run the analyzer to produce all 6 result files.