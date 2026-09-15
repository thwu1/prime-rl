A stripped ELF binary at `/app/vm_runner` implements a custom stack-based virtual machine with an undocumented instruction set. No source code, headers, or ISA documentation is provided. A reference bytecode file at `/app/reference.bc` correctly validates license keys when executed by this VM. Test vectors in `/app/test_vectors.json` provide seed/key-group pairs with expected accept(0)/reject(1) results.

The VM runner is invoked as: `./vm_runner <bytecode_file> <mem0_hex> [<mem1_hex> ...]`. It loads bytecode from the file, initialises VM memory slots from the hex arguments, executes the bytecode, and exits with the result code.

You must reverse-engineer the VM's instruction set architecture from the stripped binary using the analysis tools installed on the system (`radare2`, `gdb`, `objdump`, `readelf`, `xxd`, `strace`, `ltrace`, `strings`), then disassemble and trace through the reference bytecode to reconstruct the key validation algorithm.

Create `/app/compiler.py` — a Python program that, when run as `python3 /app/compiler.py`, produces `/app/output.bc` containing valid bytecode for this VM. The bytecode must:

1. **Correctly implement the same algorithm** as `reference.bc`: produce the same accept/reject result for any valid input (not just the provided test vectors).
2. **Meet obfuscation requirements**:
   - Shannon entropy of the raw bytecode >= 4.5 bits/byte.
   - Total instruction count >= 500 (the clean reference implementation uses ~180).
   - At least 15% of instructions must be dead code (never executed across diverse inputs).
   - At least 5 conditional branches must be opaque predicates (always resolve the same direction regardless of input).
3. **Remain well-formed**: every byte must belong to a valid instruction when parsed sequentially from offset 0. Total size must not exceed 16 KiB.