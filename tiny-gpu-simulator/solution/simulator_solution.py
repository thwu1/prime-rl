"""
Functional simulator for the tiny-gpu architecture.

Implements the ISA and SIMD execution model defined in the tiny-gpu
SystemVerilog source code, producing functionally equivalent results
to the hardware simulation.

"""


class TinyGPU:
    """Functional simulator for the tiny-gpu architecture.

    Simulates kernel execution with configurable number of cores and
    threads per block, matching the ISA semantics defined in the
    SystemVerilog source.
    """

    # Opcodes from decoder.sv (instruction[15:12])
    NOP   = 0x0
    BRnzp = 0x1
    CMP   = 0x2
    ADD   = 0x3
    SUB   = 0x4
    MUL   = 0x5
    DIV   = 0x6
    LDR   = 0x7
    STR   = 0x8
    CONST = 0x9
    RET   = 0xF

    def __init__(self, num_cores=2, threads_per_block=4):
        self.num_cores = num_cores
        self.threads_per_block = threads_per_block

    def run(self, program, data, thread_count):
        """
        Execute a kernel on the simulated GPU.

        Args:
            program: list of 16-bit integers representing program memory
            data: list of 8-bit integers representing initial data memory
            thread_count: total number of threads to launch

        Returns:
            list of 256 8-bit integers representing final data memory state
        """
        # Initialize 256-entry data memory (8-bit values)
        data_mem = [0] * 256
        for i, v in enumerate(data):
            if i < 256:
                data_mem[i] = v & 0xFF

        # Calculate total number of blocks
        tpb = self.threads_per_block
        total_blocks = (thread_count + tpb - 1) // tpb

        # Dispatch and execute blocks sequentially
        # (blocks don't interact, so sequential execution is functionally correct)
        for block_id in range(total_blocks):
            if block_id == total_blocks - 1:
                block_threads = thread_count - block_id * tpb
            else:
                block_threads = tpb
            self._execute_block(program, data_mem, block_id, block_threads)

        return data_mem

    def _execute_block(self, program, data_mem, block_id, num_threads):
        """Execute a single block of threads to completion.

        All threads in a block execute in lockstep (same PC, no branch
        divergence), matching the hardware's scheduler behavior.
        """
        # Initialize per-thread register files (16 registers each)
        regs = []
        nzp = []
        for t in range(num_threads):
            r = [0] * 16
            # Read-only SIMD registers (from registers.sv)
            r[13] = block_id & 0xFF                  # %blockIdx
            r[14] = self.threads_per_block & 0xFF     # %blockDim (always full block size)
            r[15] = t & 0xFF                          # %threadIdx
            regs.append(r)
            nzp.append(0)  # NZP register per thread (3-bit: [N, Z, P])

        pc = 0
        max_instructions = 100000  # Safety limit to prevent infinite loops

        for _ in range(max_instructions):
            if pc >= len(program):
                break

            instr = program[pc]
            opcode = (instr >> 12) & 0xF

            # RET: all threads terminate simultaneously
            if opcode == self.RET:
                break

            # NOP: advance PC, do nothing
            if opcode == self.NOP:
                pc += 1
                continue

            # Decode instruction fields (from decoder.sv)
            # All fields are extracted; which ones are used depends on opcode
            rd_addr = (instr >> 8) & 0xF      # instruction[11:8]
            rs_addr = (instr >> 4) & 0xF       # instruction[7:4]
            rt_addr = instr & 0xF              # instruction[3:0]
            nzp_cond = (instr >> 9) & 0x7      # instruction[11:9] (for BRnzp)
            imm = instr & 0xFF                 # instruction[7:0] (for CONST, BRnzp)

            next_pc = pc + 1

            # Execute instruction for each active thread
            for t in range(num_threads):
                rs_val = regs[t][rs_addr]
                rt_val = regs[t][rt_addr]

                if opcode == self.ADD:
                    if rd_addr < 13:
                        regs[t][rd_addr] = (rs_val + rt_val) & 0xFF

                elif opcode == self.SUB:
                    if rd_addr < 13:
                        regs[t][rd_addr] = (rs_val - rt_val) & 0xFF

                elif opcode == self.MUL:
                    if rd_addr < 13:
                        regs[t][rd_addr] = (rs_val * rt_val) & 0xFF

                elif opcode == self.DIV:
                    if rd_addr < 13:
                        if rt_val != 0:
                            regs[t][rd_addr] = (rs_val // rt_val) & 0xFF
                        else:
                            regs[t][rd_addr] = 0

                elif opcode == self.CONST:
                    # decoded_reg_input_mux = CONSTANT (2'b10)
                    # Register gets the 8-bit immediate value
                    if rd_addr < 13:
                        regs[t][rd_addr] = imm

                elif opcode == self.LDR:
                    # Load from data memory at address in rs
                    # (from lsu.sv: mem_read_address <= rs)
                    if rd_addr < 13:
                        regs[t][rd_addr] = data_mem[rs_val & 0xFF]

                elif opcode == self.STR:
                    # Store rt to data memory at address in rs
                    # (from lsu.sv: mem_write_address <= rs, mem_write_data <= rt)
                    data_mem[rs_val & 0xFF] = rt_val & 0xFF

                elif opcode == self.CMP:
                    # From alu.sv:
                    # alu_out_reg <= {5'b0, (rs - rt > 0), (rs - rt == 0), (rs - rt < 0)}
                    #
                    # With unsigned 8-bit operands:
                    # - (rs - rt > 0): true when the 8-bit unsigned difference is nonzero
                    #   This is true when rs != rt (both rs>rt and rs<rt wrap to positive)
                    # - (rs - rt == 0): true when rs == rt
                    # - (rs - rt < 0): always false (unsigned values are never negative)
                    diff = (rs_val - rt_val) & 0xFF
                    bit2 = 1 if diff > 0 else 0    # alu_out[2]: "N" flag
                    bit1 = 1 if diff == 0 else 0    # alu_out[1]: "Z" flag
                    bit0 = 0                         # alu_out[0]: "P" flag (always 0)
                    nzp[t] = (bit2 << 2) | (bit1 << 1) | bit0

                elif opcode == self.BRnzp:
                    # From pc.sv:
                    # if ((nzp & decoded_nzp) != 3'b0) -> branch to immediate
                    # else -> PC + 1
                    #
                    # Each thread computes its own branch decision.
                    # Hardware uses next_pc[THREADS_PER_BLOCK-1] (last thread).
                    # Since we iterate t from 0 to num_threads-1, the last
                    # thread's decision naturally overwrites next_pc.
                    if (nzp[t] & nzp_cond) != 0:
                        next_pc = imm
                    else:
                        next_pc = pc + 1

            pc = next_pc
