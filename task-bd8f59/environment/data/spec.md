# RV32I Analyzer — Interface Contract

## Overview

Create `/app/rv32i_analyzer.py` exporting four functions. The module must correctly handle the complete RV32I base integer instruction set as defined in the RISC-V Unprivileged ISA Specification (Volume I). Consult that specification for all instruction encoding details, bit-field layouts, and execution semantics.

## Supported Instructions

All RV32I base integer instructions must be handled:
- Register-register ALU: add, sub, sll, slt, sltu, xor, srl, sra, or, and
- Immediate ALU: addi, slti, sltiu, xori, ori, andi, slli, srli, srai
- Loads: lb, lh, lw, lbu, lhu
- Stores: sb, sh, sw
- Branches: beq, bne, blt, bge, bltu, bgeu
- Upper-immediate: lui, auipc
- Jumps: jal, jalr
- System: ecall (used as halt — simulation stops when encountered)

---

## Function 1: `decode_instruction(word: int) -> dict`

Decode a 32-bit RV32I instruction word. Returns a dict:

```python
{
    'type': str,       # Instruction format: 'R', 'I', 'S', 'B', 'U', or 'J'
    'opcode': int,     # 7-bit opcode value
    'rd': int | None,  # destination register (0-31), None for S/B
    'rs1': int | None, # source register 1 (0-31), None for U/J
    'rs2': int | None, # source register 2 (0-31), None for I/U/J
    'funct3': int | None,
    'funct7': int | None,  # For R-type and shift I-type
    'imm': int | None,     # Sign-extended immediate (Python int, can be negative)
    'name': str,           # Mnemonic: 'add', 'addi', 'beq', 'lui', etc.
}
```

**Immediate conventions:**
- I/S/B/J types: `imm` is a signed Python int (e.g., -8 not 0xFFFFFFF8)
- U type: `imm` is the full 32-bit value (upper 20 bits set, lower 12 zero)
- Shift I-type (slli/srli/srai): `imm` = shamt (0-31), `funct7` set
- R type: `imm` is None

---

## Function 2: `simulate(program: list[int], start_pc: int = 0, max_steps: int = 10000) -> dict`

Simulate an RV32I program.

- `program`: list of 32-bit instruction words, loaded contiguously from `start_pc`
- Instructions are fetched from `program[(pc - start_pc) // 4]`
- Register x0 is hardwired to 0 (writes are discarded)
- Memory is byte-addressable, little-endian, initialized to zero
- ECALL terminates execution
- All arithmetic is 32-bit unsigned with masking to 0xFFFFFFFF

Returns:
```python
{
    'registers': list[int],  # 32 register values (unsigned 32-bit)
    'trace': list[dict],     # One entry per executed instruction
    'steps': int,            # Number of instructions executed
    'exit_code': int,        # Value of x10 (a0) at ECALL, or -1
}
```

Each trace entry:
```python
{
    'pc': int,             # Program counter for this instruction
    'instruction': int,    # 32-bit instruction word
    'rd': int | None,      # Destination register (None for stores/branches/ecall)
    'rd_value': int | None # Value in rd after execution (None if no rd)
}
```

---

## Function 3: `find_trace_errors(program: list[int], trace: list[dict], start_pc: int = 0) -> list[dict]`

Compare a provided execution trace against correct simulation. The `trace` parameter uses the same dict format as the simulate output's trace field.

Returns a list of error dicts:
```python
{
    'step': int,       # 0-based index in the trace
    'pc': int,         # PC of the instruction
    'field': str,      # 'rd_value', 'pc', or 'instruction'
    'expected': value,  # Correct value from simulation
    'actual': value,    # Value in the provided trace
}
```

---

## Function 4: `analyze_pipeline_hazards(program: list[int]) -> list[dict]`

Statically analyze the instruction sequence for data hazards assuming a standard 5-stage in-order pipeline (IF/ID/EX/MEM/WB). Report all RAW (Read After Write) hazards where the distance between producer and consumer is at most 2. Register x0 is excluded (never causes hazards). For each source register a consumer reads, consider only the most recent prior instruction that writes to that register.

Returns list of hazard dicts:
```python
{
    'consumer_index': int,       # Index of instruction that reads
    'producer_index': int,       # Index of instruction that writes
    'register': int,             # Register number causing hazard
    'type': 'RAW',
    'distance': int,             # consumer_index - producer_index
    'stalls_no_forwarding': int,
    'stalls_with_forwarding': int,
}
```

---

## Data Formats

### Program files (`/app/programs/*.hex`)
One 32-bit instruction word per line, lowercase hex, no `0x` prefix.

### Trace files (`/app/traces/*.csv`)
Semicolon-delimited, no header. Fields: `pc;instruction;rd;rd_value`
- `pc`: 8-digit hex
- `instruction`: 8-digit hex
- `rd`: decimal register number (empty for stores/branches/ecall)
- `rd_value`: 8-digit hex (empty for stores/branches/ecall)
