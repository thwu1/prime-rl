#!/usr/bin/env python3
"""
Functional simulator for the tiny-gpu architecture.

Execution semantics derived from the SystemVerilog RTL in src/.
Models the SIMD block/thread execution model with correct register,
ALU, memory, and branch behavior.

Key implementation notes (derived from RTL):
  - CMP uses unsigned 8-bit subtraction for flag generation (alu.sv).
    alu_out[2] = (rs - rt > 0), alu_out[1] = (rs - rt == 0), alu_out[0] = (rs - rt < 0)
    Since the subtraction is unsigned 8-bit, bit 0 (P flag) is never set.
    Bit 2 (N flag) is set whenever rs != rt.
  - BRnzp checks (nzp_register & decoded_nzp) != 0 to decide branch (pc.sv).
  - Registers R13-R15 are read-only (registers.sv, write guarded by rd < 13).
  - STR rs, rt: mem[registers[rs]] = registers[rt] (lsu.sv).
  - LDR rd, rs: registers[rd] = mem[registers[rs]] (lsu.sv + registers.sv).
  - All threads in a block execute the same instruction at the same PC (scheduler.sv).
"""



class _Thread:
    """Per-thread state: registers, NZP flags, program counter."""

    __slots__ = ('registers', 'nzp', 'pc', 'done')

    def __init__(self, thread_id, block_id, block_dim):
        self.registers = [0] * 16
        self.registers[13] = block_id   # %blockIdx
        self.registers[14] = block_dim  # %blockDim
        self.registers[15] = thread_id  # %threadIdx
        self.nzp = 0b000
        self.pc = 0
        self.done = False


def simulate(program, data, thread_count, num_cores=2, threads_per_block=4):
    """
    Execute a tiny-gpu kernel and return the final data memory.

    Args:
        program: List of 16-bit instruction integers (program memory).
        data: List of 8-bit data values (initial data memory contents).
        thread_count: Total number of threads to launch.
        num_cores: Number of compute cores (affects block scheduling, not
                   functional correctness for non-overlapping writes).
        threads_per_block: Threads per block.

    Returns:
        List of 256 integers representing the final data memory state.
    """
    # Initialize 256-byte data memory
    memory = [0] * 256
    for i, val in enumerate(data):
        if i < 256:
            memory[i] = val & 0xFF

    # Calculate blocks
    total_blocks = (thread_count + threads_per_block - 1) // threads_per_block

    # Build blocks of threads
    blocks = []
    for block_id in range(total_blocks):
        threads_in_block = min(
            threads_per_block,
            thread_count - block_id * threads_per_block,
        )
        block = [
            _Thread(t, block_id, threads_per_block)
            for t in range(threads_in_block)
        ]
        blocks.append(block)

    # Execute each block.  In a functional simulation the dispatch order
    # doesn't affect correctness (kernels use non-overlapping writes).
    for block in blocks:
        _execute_block(block, program, memory)

    return memory


def _execute_block(block, program, memory):
    """Execute all threads in a block in lock-step SIMD until all hit RET."""
    max_instructions = 100_000  # safety bound
    step = 0

    while step < max_instructions:
        # Find active (non-done) threads
        active = [t for t in block if not t.done]
        if not active:
            break

        # All active threads share the same PC (no branch divergence)
        current_pc = active[0].pc
        if current_pc >= len(program):
            break

        instruction = program[current_pc]

        # Decode (mirrors decoder.sv)
        opcode = (instruction >> 12) & 0xF
        rd = (instruction >> 8) & 0xF
        rs_addr = (instruction >> 4) & 0xF
        rt_addr = instruction & 0xF
        immediate = instruction & 0xFF
        nzp_cond = (instruction >> 9) & 0x7

        for thread in active:
            # Register read (REQUEST phase in hardware)
            rs_val = thread.registers[rs_addr]
            rt_val = thread.registers[rt_addr]

            if opcode == 0b0000:        # NOP
                thread.pc = current_pc + 1

            elif opcode == 0b0001:      # BRnzp
                if (thread.nzp & nzp_cond) != 0:
                    thread.pc = immediate
                else:
                    thread.pc = current_pc + 1

            elif opcode == 0b0010:      # CMP
                # Unsigned 8-bit subtraction for flag generation (alu.sv)
                unsigned_diff = (rs_val - rt_val) & 0xFF
                n_bit = 1 if unsigned_diff > 0 else 0
                z_bit = 1 if unsigned_diff == 0 else 0
                p_bit = 0  # unsigned: never negative
                thread.nzp = (n_bit << 2) | (z_bit << 1) | p_bit
                thread.pc = current_pc + 1

            elif opcode == 0b0011:      # ADD
                result = (rs_val + rt_val) & 0xFF
                if rd < 13:
                    thread.registers[rd] = result
                thread.pc = current_pc + 1

            elif opcode == 0b0100:      # SUB
                result = (rs_val - rt_val) & 0xFF
                if rd < 13:
                    thread.registers[rd] = result
                thread.pc = current_pc + 1

            elif opcode == 0b0101:      # MUL
                result = (rs_val * rt_val) & 0xFF
                if rd < 13:
                    thread.registers[rd] = result
                thread.pc = current_pc + 1

            elif opcode == 0b0110:      # DIV
                if rt_val != 0:
                    result = (rs_val // rt_val) & 0xFF
                else:
                    result = 0
                if rd < 13:
                    thread.registers[rd] = result
                thread.pc = current_pc + 1

            elif opcode == 0b0111:      # LDR
                loaded = memory[rs_val & 0xFF]
                if rd < 13:
                    thread.registers[rd] = loaded
                thread.pc = current_pc + 1

            elif opcode == 0b1000:      # STR
                memory[rs_val & 0xFF] = rt_val & 0xFF
                thread.pc = current_pc + 1

            elif opcode == 0b1001:      # CONST
                if rd < 13:
                    thread.registers[rd] = immediate & 0xFF
                thread.pc = current_pc + 1

            elif opcode == 0b1111:      # RET
                thread.done = True

            else:
                thread.pc = current_pc + 1

        step += 1
