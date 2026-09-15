"""
Optimized kernel achieving < 17000 cycles through SIMD vectorization and VLIW packing.

Key optimizations:
1. SIMD: Process 8 batch items per iteration using valu/vload/vstore
2. VLIW: Pack independent operations into same instruction bundle
3. Loops: Use jump instructions instead of fully unrolling rounds
"""

from problem import (
    Engine,
    DebugInfo,
    SLOT_LIMITS,
    VLEN,
    N_CORES,
    SCRATCH_SIZE,
    Machine,
    Tree,
    Input,
    HASH_STAGES,
    reference_kernel,
    build_mem_image,
    reference_kernel2,
)

from collections import defaultdict


class KernelBuilder:
    def __init__(self):
        self.instrs = []
        self.scratch = {}
        self.scratch_debug = {}
        self.scratch_ptr = 0
        self.const_map = {}

    def debug_info(self):
        return DebugInfo(scratch_map=self.scratch_debug)

    def add(self, engine, slot):
        self.instrs.append({engine: [slot]})

    def emit(self, instr_dict):
        """Emit a pre-built instruction bundle."""
        self.instrs.append(instr_dict)

    def alloc_scratch(self, name=None, length=1):
        addr = self.scratch_ptr
        if name is not None:
            self.scratch[name] = addr
            self.scratch_debug[addr] = (name, length)
        self.scratch_ptr += length
        assert self.scratch_ptr <= SCRATCH_SIZE, "Out of scratch space"
        return addr

    def scratch_const(self, val, name=None):
        if val not in self.const_map:
            addr = self.alloc_scratch(name)
            self.add("load", ("const", addr, val))
            self.const_map[val] = addr
        return self.const_map[val]

    def build_kernel(
        self, forest_height: int, n_nodes: int, batch_size: int, rounds: int
    ):
        """
        Optimized kernel using SIMD vectorization and VLIW instruction packing.
        Processes VLEN=8 batch items per iteration using vector operations.
        """
        assert batch_size % VLEN == 0, f"batch_size {batch_size} must be multiple of VLEN={VLEN}"

        # --- Scalar scratch allocations ---
        tmp1 = self.alloc_scratch("tmp1")
        tmp2 = self.alloc_scratch("tmp2")
        tmp3 = self.alloc_scratch("tmp3")

        # Load problem parameters from memory header
        init_vars = [
            "rounds", "n_nodes", "batch_size", "forest_height",
            "forest_values_p", "inp_indices_p", "inp_values_p",
        ]
        for v in init_vars:
            self.alloc_scratch(v, 1)
        for i, v in enumerate(init_vars):
            self.add("load", ("const", tmp1, i))
            self.add("load", ("load", self.scratch[v], tmp1))

        # Scalar constants
        zero_s = self.scratch_const(0)
        one_s = self.scratch_const(1)
        two_s = self.scratch_const(2)

        # --- Vector scratch allocations ---
        # Each vector register occupies VLEN=8 consecutive scratch words
        v_idx = self.alloc_scratch("v_idx", VLEN)
        v_val = self.alloc_scratch("v_val", VLEN)
        v_node_val = self.alloc_scratch("v_node_val", VLEN)
        v_tmp1 = self.alloc_scratch("v_tmp1", VLEN)
        v_tmp2 = self.alloc_scratch("v_tmp2", VLEN)
        v_tmp3 = self.alloc_scratch("v_tmp3", VLEN)
        v_tmp4 = self.alloc_scratch("v_tmp4", VLEN)
        v_addr = self.alloc_scratch("v_addr", VLEN)
        v_zero = self.alloc_scratch("v_zero", VLEN)
        v_one = self.alloc_scratch("v_one", VLEN)
        v_two = self.alloc_scratch("v_two", VLEN)
        v_n_nodes = self.alloc_scratch("v_n_nodes", VLEN)

        # Hash constant vectors
        v_hash_consts = {}
        for hi, (op1, val1, op2, op3, val3) in enumerate(HASH_STAGES):
            v_c1 = self.alloc_scratch(f"v_hash_c1_{hi}", VLEN)
            v_c2 = self.alloc_scratch(f"v_hash_c2_{hi}", VLEN)
            v_hash_consts[hi] = (v_c1, v_c2)

        # Loop counter scratch
        s_round = self.alloc_scratch("s_round")
        s_batch_i = self.alloc_scratch("s_batch_i")
        s_vec_iters = self.alloc_scratch("s_vec_iters")
        s_cur_indices_addr = self.alloc_scratch("s_cur_indices_addr")
        s_cur_values_addr = self.alloc_scratch("s_cur_values_addr")
        s_round_limit = self.alloc_scratch("s_round_limit")
        s_cond = self.alloc_scratch("s_cond")

        # Scratch for scalar loads of individual node values (can't vload non-contiguous)
        s_node_addrs = []
        for lane in range(VLEN):
            s_node_addrs.append(self.alloc_scratch(f"s_node_addr_{lane}"))

        self.add("flow", ("pause",))

        # --- Initialize vector constants ---
        # Broadcast scalar constants to vectors
        self.emit({"valu": [("vbroadcast", v_zero, zero_s)]})
        self.emit({"valu": [("vbroadcast", v_one, one_s)]})
        self.emit({"valu": [("vbroadcast", v_two, two_s)]})
        self.emit({"valu": [("vbroadcast", v_n_nodes, self.scratch["n_nodes"])]})

        # Initialize hash constant vectors
        for hi, (op1, val1, op2, op3, val3) in enumerate(HASH_STAGES):
            c1_scalar = self.scratch_const(val1)
            c2_scalar = self.scratch_const(val3)
            v_c1, v_c2 = v_hash_consts[hi]
            self.emit({"valu": [
                ("vbroadcast", v_c1, c1_scalar),
                ("vbroadcast", v_c2, c2_scalar),
            ]})

        # Compute number of vector iterations
        vec_iters = batch_size // VLEN
        self.emit({"load": [("const", s_vec_iters, vec_iters)]})
        self.emit({"load": [("const", s_round_limit, rounds)]})

        # --- Outer loop: rounds ---
        self.emit({"load": [("const", s_round, 0)]})
        round_loop_start = len(self.instrs)

        # --- Inner loop: vector iterations over batch ---
        # s_cur_indices_addr = inp_indices_p
        # s_cur_values_addr = inp_values_p
        self.emit({"alu": [
            ("+", s_cur_indices_addr, self.scratch["inp_indices_p"], zero_s),
            ("+", s_cur_values_addr, self.scratch["inp_values_p"], zero_s),
        ], "load": [("const", s_batch_i, 0)]})

        batch_loop_start = len(self.instrs)

        # --- Load indices and values (can vload since they're contiguous) ---
        self.emit({"load": [
            ("vload", v_idx, s_cur_indices_addr),
            ("vload", v_val, s_cur_values_addr),
        ]})

        # --- Load node values: node_val = mem[forest_values_p + idx] ---
        # Need to compute individual addresses since idx values are non-contiguous
        # v_addr[lane] = forest_values_p + v_idx[lane]
        self.emit({"valu": [
            ("vbroadcast", v_addr, self.scratch["forest_values_p"]),
        ]})
        self.emit({"valu": [
            ("+", v_addr, v_addr, v_idx),
        ]})

        # Scatter-load: load each node value individually from non-contiguous addresses
        # We need 8 scalar loads, but only have 2 load slots per cycle
        # So this takes 4 cycles
        for lane_pair in range(0, VLEN, 2):
            loads = []
            for lane_off in range(2):
                lane = lane_pair + lane_off
                loads.append(("load_offset", v_node_val, v_addr, lane))
            self.emit({"load": loads})

        # --- XOR: val = val ^ node_val ---
        self.emit({"valu": [("^", v_val, v_val, v_node_val)]})

        # --- Hash function: 6 stages, each 3 ALU ops ---
        for hi, (op1, val1, op2, op3, val3) in enumerate(HASH_STAGES):
            v_c1, v_c2 = v_hash_consts[hi]
            # tmp1 = val op1 const1
            # tmp2 = val op3 const2  (shift)
            # These two are independent, can pack in same cycle
            self.emit({"valu": [
                (op1, v_tmp1, v_val, v_c1),
                (op3, v_tmp2, v_val, v_c2),
            ]})
            # val = tmp1 op2 tmp2
            self.emit({"valu": [(op2, v_val, v_tmp1, v_tmp2)]})

        # --- Branch logic: idx = 2*idx + (1 if val%2==0 else 2) ---
        # tmp1 = val % 2
        # tmp3 = 2*idx (independent, pack here)
        self.emit({"valu": [
            ("%", v_tmp1, v_val, v_two),
            ("*", v_tmp3, v_idx, v_two),
        ]})
        # cond = (tmp1 == 0)
        self.emit({"valu": [("==", v_tmp1, v_tmp1, v_zero)]})
        # offset = select(cond, 1, 2)
        self.emit({"flow": [("vselect", v_tmp2, v_tmp1, v_one, v_two)]})
        # idx = 2*idx + offset
        self.emit({"valu": [("+", v_idx, v_tmp3, v_tmp2)]})

        # --- Wrap: idx = (idx < n_nodes) ? idx : 0 ---
        self.emit({"valu": [("<", v_tmp1, v_idx, v_n_nodes)]})
        self.emit({"flow": [("vselect", v_idx, v_tmp1, v_idx, v_zero)]})

        # --- Store results back to memory ---
        self.emit({"store": [
            ("vstore", s_cur_indices_addr, v_idx),
            ("vstore", s_cur_values_addr, v_val),
        ]})

        # --- Advance pointers and loop ---
        vlen_const = self.scratch_const(VLEN)
        self.emit({"alu": [
            ("+", s_cur_indices_addr, s_cur_indices_addr, vlen_const),
            ("+", s_cur_values_addr, s_cur_values_addr, vlen_const),
            ("+", s_batch_i, s_batch_i, one_s),
        ]})
        self.emit({"alu": [("<", s_cond, s_batch_i, s_vec_iters)]})
        self.emit({"flow": [("cond_jump", s_cond, batch_loop_start)]})

        # --- End of inner loop, advance round counter ---
        self.emit({"alu": [("+", s_round, s_round, one_s)]})
        self.emit({"alu": [("<", s_cond, s_round, s_round_limit)]})
        self.emit({"flow": [("cond_jump", s_cond, round_loop_start)]})

        # Final pause
        self.emit({"flow": [("pause",)]})


BASELINE = 147734
