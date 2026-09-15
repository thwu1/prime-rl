You are given a scrambled microcode ROM dump from a simplified 8086-inspired CPU. The ROM contains 128 micro-operations, each 24 bits wide, stored as a raw binary file. The bits within each word have been physically permuted by a fixed column permutation applied during die fabrication — the same permutation applies to every word.

Your task is to reverse-engineer the bit permutation using cross-reference data in a SQLite database, decode the full ROM, produce a control flow graph visualization, and answer specific questions about the ROM's contents. Write your results to `/app/answers.json`.

## Files in `/app/`

- `rom.bin` — The scrambled microcode ROM as a **raw binary** (384 bytes: 128 entries × 3 bytes each, big-endian 24-bit words). Use `xxd`, `od`, or equivalent to inspect.
- `microcode.db` — **SQLite database** containing the opcode translation table (`translations`), known patent micro-op listings (`patent_words`), and encoding references (`registers`, `alu_ops`, `ctrl_ops`, `field_layout`, `notes`). Use `sqlite3` to query.
- `field_spec.txt` — Describes the 24-bit micro-op field layout and the permutation model.

## What to produce

### 1. `/app/answers.json`

Write a JSON file with the following keys:

- **`permutation`** — The permutation P as a list of 24 integers, where `physical_bit[i] = logical_bit[P[i]]`.
- **`decoded_words`** — The decoded (logical) 24-bit values at ROM addresses 10, 25, 49, 75, and 100, as hex strings (e.g. `"0x00ABCD"`).
- **`end_count`** — Integer count of micro-ops whose `ctrl` field equals 1 (END).
- **`alu_histogram`** — Object mapping ALU operation names to counts across all 128 micro-ops.
- **`bug`** — Object with keys `"address"`, `"field"`, `"actual_value"`, `"correct_value"` identifying a discrepancy between the patent listing and the actual ROM for the REP STOSW routine.
- **`unique_register_pairs`** — Integer count of distinct (src, dst) register pairs across all 128 micro-ops.
- **`cfg_edge_count`** — Total number of edges in the microcode control flow graph (NEXT→next addr counts as 1 edge; JZ/JNZ count as 2 edges each — branch target + fallthrough; JMP counts as 1 edge; END/HALT have 0 outgoing edges).

### 2. `/app/microcode_cfg.dot`

A Graphviz DOT file representing the control flow graph of the decoded microcode. Requirements:
- Each micro-op address is a node labeled with its address and decoded fields.
- Edges represent control flow: sequential for NEXT, branch targets for JZ/JNZ/JMP, no outgoing edges for END/HALT.
- Nodes are grouped into subgraph clusters by instruction, using the translation table from `microcode.db`.

### 3. `/app/microcode_cfg.svg`

The control flow graph rendered as SVG by running `dot` from Graphviz.