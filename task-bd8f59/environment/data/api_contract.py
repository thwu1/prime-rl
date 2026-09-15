"""
RV32I Analyzer — API Contract

Implement these four functions in /app/rv32i_analyzer.py.
Consult the RISC-V unprivileged ISA specification for encoding and
execution semantics of the RV32I base integer instruction set.
"""


def decode_instruction(word: int) -> dict:
    """Decode a 32-bit RV32I instruction word into its fields.

    Returns a dict with keys:
        type:   str            — instruction format identifier
        opcode: int            — 7-bit opcode field
        rd:     int or None    — destination register (0–31)
        rs1:    int or None    — source register 1 (0–31)
        rs2:    int or None    — source register 2 (0–31)
        funct3: int or None
        funct7: int or None
        imm:    int or None    — decoded immediate (signed Python int where applicable)
        name:   str            — instruction mnemonic (e.g. 'add', 'lw', 'beq')
    """
    raise NotImplementedError


def simulate(program: list, start_pc: int = 0, max_steps: int = 10000) -> dict:
    """Execute an RV32I program and return results.

    Args:
        program:   list of 32-bit instruction words (int), loaded contiguously
                   from start_pc.
        start_pc:  starting program counter value.
        max_steps: maximum number of instructions to execute.

    Returns a dict with keys:
        registers: list of 32 register values (unsigned 32-bit ints)
        trace:     list of dicts, one per executed instruction, each with:
                       pc: int, instruction: int,
                       rd: int or None, rd_value: int or None
        steps:     int — total instructions executed
        exit_code: int — value of register x10 at halt, or -1
    """
    raise NotImplementedError


def find_trace_errors(program: list, trace: list, start_pc: int = 0) -> list:
    """Detect discrepancies between a provided execution trace and correct
    execution.

    Args:
        program:  list of 32-bit instruction words.
        trace:    list of dicts with keys: pc, instruction, rd, rd_value.
        start_pc: starting program counter.

    Returns a list of error dicts, each with keys:
        step: int, pc: int, field: str, expected: value, actual: value
    """
    raise NotImplementedError


def analyze_pipeline_hazards(program: list) -> list:
    """Identify data hazards in an instruction sequence for a standard
    in-order pipeline.

    Args:
        program: list of 32-bit instruction words.

    Returns a list of hazard dicts, each with keys:
        consumer_index: int        — instruction index that reads
        producer_index: int        — instruction index that wrote
        register:       int        — register causing the hazard
        type:           str        — hazard classification
        distance:       int        — consumer_index - producer_index
        stalls_no_forwarding:  int — stall cycles without bypassing
        stalls_with_forwarding: int — stall cycles with bypassing
    """
    raise NotImplementedError
