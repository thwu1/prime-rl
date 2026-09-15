Build a verifier for BPF programs stored as ELF object files.

BPF ELF object files are located in `/app/objects/`. The complete specification — ELF section layout, instruction encoding, register model, and safety rules — is in `/app/spec.md`.

Create `/app/verifier.py` that accepts a path to a BPF ELF `.o` file and outputs a JSON object to stdout:

```json
{"verdict": "accept", "disasm": ["r0 = 2", "exit"]}
```

or

```json
{"verdict": "reject", "reason": "<category>", "disasm": ["r0 = r7", "exit"]}
```

Rejection categories: `uninit_reg`, `null_ptr_deref`, `pkt_bounds`, `loop`, `unreachable`, `no_exit`.

The `disasm` field must contain BPF instruction mnemonics as produced by `llvm-objdump-18 -d --no-show-raw-insn`, one entry per instruction in program order.

BPF analysis tools are installed: `llvm-objdump-18` (BPF disassembler), `readelf` (ELF section inspector), `objcopy` (ELF section extractor), `xxd` and `hexdump` (hex viewers). Use these to inspect the ELF structure and understand the bytecode before building the verifier.