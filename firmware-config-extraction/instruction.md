A stripped ELF binary at `/app/firmware` is a firmware integrity checker for a compromised IoT device. It contains a custom bytecode virtual machine that processes embedded configuration data through multiple encryption layers. The binary only outputs an integrity verdict — it never reveals the configuration or VM internals.

Your objective is to fully reverse-engineer the VM, extract the hidden configuration, build a working emulator, and demonstrate mastery of the discovered instruction set by authoring new bytecode.

Produce four files:

**`/app/opcodes.json`**: A JSON object documenting every distinct operation in the VM's instruction set. Each key is a hex string (e.g. `"0x10"`), each value has `"size"` (total byte count including opcode) and `"description"` (what it does). Include all operations present in the interpreter, even those not exercised by the embedded bytecode.

**`/app/config_dump.txt`**: The complete decrypted configuration — one `KEY=VALUE` entry per line, 4 lines total.

**`/app/emulator.py`**: A standalone VM emulator. Interface: `python3 /app/emulator.py <bytecode_file> [data_file]`. Reads bytecode (and optionally a data table) from binary files, executes the VM, and prints output to stdout. When no data file is provided, uses an empty data table. Must faithfully reproduce the binary's VM behavior on arbitrary valid bytecode.

**`/app/payload.bin`**: A raw bytecode program (at most 64 bytes) that, when executed by your emulator with no data file, outputs exactly the string `ANALYSIS_PASS`. This bytecode must use only valid instructions from the ISA you documented.

`radare2` is pre-installed.