
"""tiny-gpu cycle-accurate simulator."""


class TinyGPU:
    """Simulates the tiny-gpu architecture: multi-core SIMD GPU with block dispatch."""

    def __init__(self, num_cores=2, threads_per_block=4,
                 data_mem_channels=4, program_mem_channels=1):
        self.num_cores = num_cores
        self.threads_per_block = threads_per_block
        self.data_mem_channels = data_mem_channels
        self.program_mem_channels = program_mem_channels
        self.program_memory = [0] * 256
        self.data_memory = [0] * 256

    def load_program(self, program: list) -> None:
        """Load program (list of 16-bit instruction words) into program memory."""
        for i, word in enumerate(program):
            self.program_memory[i] = word & 0xFFFF

    def load_data(self, data: list) -> None:
        """Load data (list of 8-bit values) into data memory."""
        for i, val in enumerate(data):
            self.data_memory[i] = val & 0xFF

    def run(self, thread_count: int) -> dict:
        """Execute kernel with given thread count.

        Returns dict with 'data_memory' (list of 256 ints) and 'cycles' (int).
        """
        total_blocks = (thread_count + self.threads_per_block - 1) // self.threads_per_block
        total_cycles = 0
        blocks_done = 0

        while blocks_done < total_blocks:
            # Dispatch up to num_cores blocks in parallel (matching dispatcher behavior)
            batch_size = min(self.num_cores, total_blocks - blocks_done)
            max_block_cycles = 0
            for b in range(batch_size):
                block_id = blocks_done + b
                bt = min(self.threads_per_block,
                         thread_count - block_id * self.threads_per_block)
                c = self._execute_block(block_id, bt)
                max_block_cycles = max(max_block_cycles, c)
            total_cycles += max_block_cycles
            blocks_done += batch_size

        return {'data_memory': list(self.data_memory), 'cycles': total_cycles}

    def _execute_block(self, block_id: int, num_threads: int) -> int:
        """Execute a single block on a core. Returns cycle count."""
        # Initialize per-thread register files
        regs = []
        nzp_vals = []
        for t in range(num_threads):
            r = [0] * 16
            r[13] = block_id                 # %blockIdx
            r[14] = self.threads_per_block    # %blockDim
            r[15] = t                         # %threadIdx
            regs.append(r)
            nzp_vals.append(0)

        pc = 0
        cycles = 0
        limit = 100000  # safety limit to prevent infinite loops

        while cycles < limit:
            instr = self.program_memory[pc]
            opcode = (instr >> 12) & 0xF

            # RET: end of kernel for this block
            if opcode == 0xF:
                cycles += 1
                break

            # Decode instruction fields
            rd = (instr >> 8) & 0xF
            rs_a = (instr >> 4) & 0xF
            rt_a = instr & 0xF
            nzp_cond = (instr >> 9) & 0x7
            imm = instr & 0xFF

            next_pc = pc + 1

            # Execute instruction for each thread (SIMD)
            for t in range(num_threads):
                rs_v = regs[t][rs_a]
                rt_v = regs[t][rt_a]

                if opcode == 0x0:
                    # NOP
                    pass

                elif opcode == 0x2:
                    # CMP: signed comparison, set NZP
                    diff = rs_v - rt_v
                    if diff < 0:
                        nzp_vals[t] = 4   # N (negative)
                    elif diff == 0:
                        nzp_vals[t] = 2   # Z (zero)
                    else:
                        nzp_vals[t] = 1   # P (positive)

                elif opcode == 0x3:
                    # ADD
                    if rd < 13:
                        regs[t][rd] = (rs_v + rt_v) & 0xFF

                elif opcode == 0x4:
                    # SUB
                    if rd < 13:
                        regs[t][rd] = (rs_v - rt_v) & 0xFF

                elif opcode == 0x5:
                    # MUL
                    if rd < 13:
                        regs[t][rd] = (rs_v * rt_v) & 0xFF

                elif opcode == 0x6:
                    # DIV
                    if rd < 13 and rt_v != 0:
                        regs[t][rd] = (rs_v // rt_v) & 0xFF

                elif opcode == 0x7:
                    # LDR: load from data memory
                    if rd < 13:
                        regs[t][rd] = self.data_memory[rs_v & 0xFF]

                elif opcode == 0x8:
                    # STR: store to data memory
                    self.data_memory[rs_v & 0xFF] = rt_v & 0xFF

                elif opcode == 0x9:
                    # CONST: load immediate
                    if rd < 13:
                        regs[t][rd] = imm

            # BRnzp: shared PC decision using last active thread
            # (no branch divergence — all threads share same PC)
            if opcode == 0x1:
                last_nzp = nzp_vals[num_threads - 1]
                if last_nzp & nzp_cond:
                    next_pc = imm

            pc = next_pc
            cycles += 1

        return cycles
