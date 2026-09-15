"""
tiny-gpu functional simulator

Simulates execution of tiny-gpu machine code programs. Models the GPU's
block-based thread dispatch, per-thread register files, 8-bit unsigned
arithmetic with wrapping, memory load/store, CMP/NZP comparison flags,
conditional branching, and shared program counter (no branch divergence).

Architecture (from Verilog source):
  - Data memory: 256 x 8-bit
  - Program memory: 256 x 16-bit instructions
  - Registers per thread: R0-R12 (r/w), R13=%blockIdx, R14=%blockDim, R15=%threadIdx
  - CMP sets NZP flags via unsigned subtraction: N=(diff>0), Z=(diff==0), P=0
  - All threads in a block share one PC; last thread's branch decision wins
"""

import math

# Opcodes (from decoder.sv)
NOP   = 0b0000
BR    = 0b0001
CMP   = 0b0010
ADD   = 0b0011
SUB   = 0b0100
MUL   = 0b0101
DIV   = 0b0110
LDR   = 0b0111
STR   = 0b1000
CONST = 0b1001
RET   = 0b1111


def simulate(program, data, thread_count, num_cores=2, threads_per_block=4):
    """
    Execute a tiny-gpu program and return final state.

    Args:
        program: list of 16-bit int machine code words
        data: list of initial data memory values (8-bit)
        thread_count: total number of threads to launch
        num_cores: number of GPU cores (functional sim processes blocks
                   sequentially, so this only affects block count calculation)
        threads_per_block: threads per block

    Returns:
        dict with keys:
            'data_memory': list of 256 ints (final 8-bit data memory)
            'num_blocks': number of thread blocks dispatched
    """
    # Initialize data memory (256 bytes)
    data_memory = [0] * 256
    for i, v in enumerate(data):
        if i < 256:
            data_memory[i] = v & 0xFF

    # Calculate blocks
    num_blocks = math.ceil(thread_count / threads_per_block) if thread_count > 0 else 0

    # Process each block
    for block_id in range(num_blocks):
        # Number of active threads in this block
        if block_id == num_blocks - 1:
            block_threads = thread_count - block_id * threads_per_block
        else:
            block_threads = threads_per_block

        # Initialize per-thread register files (16 registers each)
        regs = []
        nzp_flags = []
        for t in range(block_threads):
            r = [0] * 16
            r[13] = block_id          # %blockIdx
            r[14] = threads_per_block  # %blockDim (always full block size)
            r[15] = t                  # %threadIdx
            regs.append(r)
            nzp_flags.append(0b000)

        # Execute instructions with shared PC
        pc = 0
        max_instructions = len(program) * 1000  # safety limit
        executed = 0

        while pc < len(program) and executed < max_instructions:
            instr = program[pc]
            opcode = (instr >> 12) & 0xF
            rd_addr = (instr >> 8) & 0xF
            rs_addr = (instr >> 4) & 0xF
            rt_addr = instr & 0xF
            nzp_cond = (instr >> 9) & 0x7
            immediate = instr & 0xFF

            if opcode == RET:
                break

            if opcode == NOP:
                pc += 1
                executed += 1
                continue

            next_pc = pc + 1

            for t in range(block_threads):
                rs_val = regs[t][rs_addr]
                rt_val = regs[t][rt_addr]

                if opcode == ADD:
                    if rd_addr < 13:
                        regs[t][rd_addr] = (rs_val + rt_val) & 0xFF
                elif opcode == SUB:
                    if rd_addr < 13:
                        regs[t][rd_addr] = (rs_val - rt_val) & 0xFF
                elif opcode == MUL:
                    if rd_addr < 13:
                        regs[t][rd_addr] = (rs_val * rt_val) & 0xFF
                elif opcode == DIV:
                    if rd_addr < 13 and rt_val != 0:
                        regs[t][rd_addr] = (rs_val // rt_val) & 0xFF
                elif opcode == CMP:
                    # Unsigned 8-bit subtraction for NZP (matches ALU Verilog)
                    diff = (rs_val - rt_val) & 0xFF
                    n = 1 if diff > 0 else 0
                    z = 1 if diff == 0 else 0
                    p = 0  # unsigned: never negative
                    nzp_flags[t] = (n << 2) | (z << 1) | p
                elif opcode == BR:
                    # Branch: last thread's decision determines next_pc
                    if (nzp_cond & nzp_flags[t]) != 0:
                        next_pc = immediate
                    else:
                        next_pc = pc + 1
                elif opcode == LDR:
                    if rd_addr < 13:
                        addr = rs_val & 0xFF
                        regs[t][rd_addr] = data_memory[addr]
                elif opcode == STR:
                    addr = rs_val & 0xFF
                    data_memory[addr] = rt_val & 0xFF
                elif opcode == CONST:
                    if rd_addr < 13:
                        regs[t][rd_addr] = immediate & 0xFF

            pc = next_pc
            executed += 1

    return {
        'data_memory': data_memory,
        'num_blocks': num_blocks,
    }
