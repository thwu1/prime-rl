#!/usr/bin/env python3

"""Gold solution: Multi-backend quantum error correction pipeline."""

import json
import math
from itertools import combinations
from pathlib import Path

import numpy as np
from z3 import Bool, Not, Optimize, Xor, simplify


# ─── GF(2) Linear Algebra ────────────────────────────────────────

def gf2_rank(M):
    """Compute rank of binary matrix over GF(2)."""
    A = np.array(M, dtype=np.int8).copy()
    rows, cols = A.shape
    rank = 0
    for col in range(cols):
        pivot = None
        for row in range(rank, rows):
            if A[row, col] == 1:
                pivot = row
                break
        if pivot is None:
            continue
        A[[rank, pivot]] = A[[pivot, rank]]
        for row in range(rows):
            if row != rank and A[row, col] == 1:
                A[row] = (A[row] + A[rank]) % 2
        rank += 1
    return rank


def gf2_kernel(M):
    """Compute kernel of M over GF(2). Returns matrix whose rows span ker(M)."""
    A = np.array(M, dtype=np.int8).copy()
    m, n = A.shape
    pivot_cols = []
    row = 0
    for col in range(n):
        found = False
        for r in range(row, m):
            if A[r, col] == 1:
                A[[row, r]] = A[[r, row]]
                found = True
                break
        if not found:
            continue
        for r in range(m):
            if r != row and A[r, col] == 1:
                A[r] = (A[r] + A[row]) % 2
        pivot_cols.append(col)
        row += 1

    free_cols = [c for c in range(n) if c not in pivot_cols]
    kernel_vectors = []
    for fc in free_cols:
        v = np.zeros(n, dtype=np.int8)
        v[fc] = 1
        for i, pc in enumerate(pivot_cols):
            v[pc] = A[i, fc]
        kernel_vectors.append(v)

    if not kernel_vectors:
        return np.zeros((0, n), dtype=np.int8)
    return np.array(kernel_vectors, dtype=np.int8)


# ─── Stabilizer Parser ───────────────────────────────────────────

def parse_stabilizer_file(filepath):
    """Parse a .stab file with Pauli string generators into CSS check matrices."""
    generators = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            generators.append(line)

    n = len(generators[0])
    x_generators = []
    z_generators = []

    for gen in generators:
        assert len(gen) == n, f"Generator length {len(gen)} != {n}"
        has_x = any(c in ("X", "Y") for c in gen)
        has_z = any(c in ("Z", "Y") for c in gen)

        if has_x and not has_z:
            row = [1 if c == "X" else 0 for c in gen]
            x_generators.append(row)
        elif has_z and not has_x:
            row = [1 if c == "Z" else 0 for c in gen]
            z_generators.append(row)
        else:
            raise ValueError(f"Non-CSS generator: {gen}")

    Hx = np.array(x_generators, dtype=np.int8)
    Hz = np.array(z_generators, dtype=np.int8)
    return n, Hx, Hz


def compute_logical_operators(Hx, Hz, n):
    """Compute logical X and Z operators for a CSS code via GF(2) quotient."""
    rx = gf2_rank(Hx)
    rz = gf2_rank(Hz)
    k = n - rx - rz

    if k == 0:
        return np.zeros((0, n), dtype=np.int8), np.zeros((0, n), dtype=np.int8)

    # Z logicals: in ker(Hx) but not in rowspace(Hz)
    ker_Hx = gf2_kernel(Hx)
    Lz = _find_independent_of_rowspace(ker_Hx, Hz, k)

    # X logicals: in ker(Hz) but not in rowspace(Hx)
    ker_Hz = gf2_kernel(Hz)
    Lx = _find_independent_of_rowspace(ker_Hz, Hx, k)

    # Normalize so Lx @ Lz^T = I_k mod 2
    Lx, Lz = _normalize_logicals(Lx, Lz, k)

    return Lx, Lz


def _find_independent_of_rowspace(kernel_vecs, generators, k):
    """Find k vectors from kernel that are linearly independent of rowspace."""
    gen_rank = gf2_rank(generators)
    logicals = []
    basis = generators.copy() if generators.shape[0] > 0 else np.zeros(
        (0, kernel_vecs.shape[1]), dtype=np.int8
    )

    for v in kernel_vecs:
        test = np.vstack([basis, v.reshape(1, -1)])
        if gf2_rank(test) > gf2_rank(basis):
            logicals.append(v.copy())
            basis = test
            if len(logicals) == k:
                break

    return np.array(logicals, dtype=np.int8)


def _normalize_logicals(Lx, Lz, k):
    """Normalize logical operators so Lx @ Lz^T = I_k mod 2."""
    Lx = Lx.copy()
    Lz = Lz.copy()

    # Row operations on Lx to make overlap = I_k
    overlap = Lx @ Lz.T % 2
    for i in range(k):
        # Find pivot in column i
        pivot = None
        for r in range(i, k):
            if overlap[r, i] == 1:
                pivot = r
                break
        if pivot is None:
            raise ValueError("Cannot normalize: degenerate overlap matrix")
        if pivot != i:
            overlap[[i, pivot]] = overlap[[pivot, i]]
            Lx[[i, pivot]] = Lx[[pivot, i]]
        for r in range(k):
            if r != i and overlap[r, i] == 1:
                overlap[r] = (overlap[r] + overlap[i]) % 2
                Lx[r] = (Lx[r] + Lx[i]) % 2

    # Column operations on Lz
    overlap = Lx @ Lz.T % 2
    for j in range(k):
        for c in range(k):
            if c != j and overlap[j, c] == 1:
                Lz[c] = (Lz[c] + Lz[j]) % 2
        overlap = Lx @ Lz.T % 2

    return Lx, Lz


def compute_distance(Hx, Hz, n):
    """Compute code distance by searching for minimum-weight non-trivial logical."""
    hx_rank = gf2_rank(Hx)
    hz_rank = gf2_rank(Hz)

    for w in range(1, n + 1):
        for combo in combinations(range(n), w):
            v = np.zeros(n, dtype=np.int8)
            for idx in combo:
                v[idx] = 1
            # Check Z-type: in ker(Hx) and not in rowspace(Hz)
            if np.all(Hx @ v % 2 == 0):
                test = np.vstack([Hz, v.reshape(1, -1)])
                if gf2_rank(test) > hz_rank:
                    return w
            # Check X-type: in ker(Hz) and not in rowspace(Hx)
            if np.all(Hz @ v % 2 == 0):
                test = np.vstack([Hx, v.reshape(1, -1)])
                if gf2_rank(test) > hx_rank:
                    return w
    return n


# ─── MaxSAT Decoder ──────────────────────────────────────────────

class LightsOutDecoder:
    """MaxSAT-based LightsOut decoder using Z3 with XOR parity chain constraints."""

    def __init__(self, check_matrix):
        H = np.array(check_matrix, dtype=np.int8)
        self.num_checks = H.shape[0]
        self.num_qubits = H.shape[1]
        self.lights_to_switches = {}
        for i in range(self.num_checks):
            self.lights_to_switches[i] = [
                j for j in range(self.num_qubits) if H[i, j] == 1
            ]
        self.switch_vars = None
        self.helper_vars = {}
        self.optimizer = Optimize()
        self._preconstructed = False

    def preconstruct(self, weights=None):
        self.switch_vars = [Bool(f"s_{j}") for j in range(self.num_qubits)]

        for light, switches in self.lights_to_switches.items():
            k = len(switches)
            if k > 1:
                self.helper_vars[light] = [
                    Bool(f"h_{light}_{i}") for i in range(k - 1)
                ]
                helpers = self.helper_vars[light]
                for i in range(1, k - 1):
                    c = Xor(self.switch_vars[switches[i]], helpers[i]) == helpers[i - 1]
                    self.optimizer.add(simplify(c))
                c = self.switch_vars[switches[-1]] == helpers[-1]
                self.optimizer.add(simplify(c))

        if weights is not None and len(weights) > 0:
            for j, w in enumerate(weights):
                self.optimizer.add_soft(Not(self.switch_vars[j]), w)
        else:
            for sv in self.switch_vars:
                self.optimizer.add_soft(Not(sv))

        self._preconstructed = True

    def solve(self, syndrome):
        assert self._preconstructed
        self.optimizer.push()
        self.optimizer.set("timeout", 60000)

        for light_idx, val in enumerate(syndrome):
            switches = self.lights_to_switches[light_idx]
            k = len(switches)
            if k == 1:
                c = self.switch_vars[switches[0]] == bool(val)
            else:
                helpers = self.helper_vars[light_idx]
                c = Xor(self.switch_vars[switches[0]], helpers[0]) == bool(val)
            self.optimizer.add(simplify(c))

        result = self.optimizer.check()
        if str(result) != "sat":
            self.optimizer.pop()
            return [0] * self.num_qubits, False

        model = self.optimizer.model()
        correction = [1 if model[sv] else 0 for sv in self.switch_vars]
        self.optimizer.pop()
        return correction, True


# ─── BP+OSD Decoder ───────────────────────────────────────────────

class BpOsdDecoderWrapper:
    """Wrapper around ldpc library's BpOsdDecoder."""

    def __init__(self, check_matrix, error_rate=0.05):
        from ldpc import BpOsdDecoder

        H = np.array(check_matrix, dtype=np.uint8)
        self.decoder = BpOsdDecoder(
            H,
            error_rate=error_rate,
            bp_method="ms",
            max_iter=50,
            osd_method="osd_cs",
            osd_order=7,
        )

    def solve(self, syndrome):
        syn = np.array(syndrome, dtype=np.uint8)
        correction = self.decoder.decode(syn)
        return correction.tolist(), True


# ─── Pipeline ─────────────────────────────────────────────────────

def load_code(code_name):
    with open(f"/app/codes/{code_name}.json") as f:
        return json.load(f)


def get_check_matrix(code_data, error_type):
    return np.array(
        code_data["Hx"] if error_type == "Z" else code_data["Hz"], dtype=np.int8
    )


def get_logical_check(code_data, error_type):
    return np.array(
        code_data["Lx"] if error_type == "Z" else code_data["Lz"], dtype=np.int8
    )


def decode_single(task, code_data, maxsat_decoder, bposd_decoder):
    """Run a single decoding task with both backends."""
    H = get_check_matrix(code_data, task["error_type"])
    L = get_logical_check(code_data, task["error_type"])
    error = np.array(task["error"], dtype=np.int8)
    syndrome = (H @ error % 2).tolist()
    lights = [bool(s) for s in syndrome]

    result = {}

    # MaxSAT decoding
    weights = None
    if task.get("weighted", False) and "qubit_error_rates" in task:
        rates = task["qubit_error_rates"]
        weights = [math.log((1 - p) / p) if 0 < p < 1 else 0 for p in rates]

    if weights is not None:
        # Build fresh decoder with custom weights for weighted tasks
        weighted_decoder = LightsOutDecoder(H.tolist())
        weighted_decoder.preconstruct(weights=weights)
        maxsat_corr, maxsat_ok = weighted_decoder.solve(lights)
    else:
        maxsat_corr, maxsat_ok = maxsat_decoder.solve(lights)

    maxsat_arr = np.array(maxsat_corr, dtype=np.int8)
    maxsat_weight = int(np.sum(maxsat_arr))
    maxsat_residual = (error + maxsat_arr) % 2
    maxsat_logical = bool((L @ maxsat_residual % 2).any())
    maxsat_resolved = bool(
        np.array_equal(H @ maxsat_arr % 2, np.array(syndrome, dtype=np.int8))
    )

    result["maxsat"] = {
        "correction": maxsat_corr,
        "weight": maxsat_weight,
        "is_logical_error": maxsat_logical,
        "syndrome_resolved": maxsat_resolved,
    }

    # BP+OSD decoding (skip for weighted tasks)
    if not task.get("weighted", False):
        bposd_corr, bposd_ok = bposd_decoder.solve(syndrome)
        bposd_arr = np.array(bposd_corr, dtype=np.int8)
        bposd_weight = int(np.sum(bposd_arr))
        bposd_residual = (error + bposd_arr) % 2
        bposd_logical = bool((L @ bposd_residual % 2).any())
        bposd_resolved = bool(
            np.array_equal(H @ bposd_arr % 2, np.array(syndrome, dtype=np.int8))
        )

        result["bposd"] = {
            "correction": bposd_corr,
            "weight": bposd_weight,
            "is_logical_error": bposd_logical,
            "syndrome_resolved": bposd_resolved,
        }

    return result


def simulate_task(task, code_data, maxsat_decoder, bposd_decoder):
    """Run Monte Carlo simulation with both backends."""
    H = get_check_matrix(code_data, task["error_type"])
    L = get_logical_check(code_data, task["error_type"])
    n = code_data["n"]
    error_rate = task["error_rate"]
    num_trials = task["num_trials"]
    seed = task["seed"]

    rng = np.random.default_rng(seed)
    maxsat_logical_errors = 0
    bposd_logical_errors = 0

    for _ in range(num_trials):
        error = rng.choice(
            [0, 1], size=n, p=[1 - error_rate, error_rate]
        ).astype(np.int8)

        syndrome = (H @ error % 2).tolist()
        lights = [bool(s) for s in syndrome]

        # MaxSAT decode
        maxsat_corr, _ = maxsat_decoder.solve(lights)
        maxsat_arr = np.array(maxsat_corr, dtype=np.int8)
        maxsat_residual = (error + maxsat_arr) % 2
        if (L @ maxsat_residual % 2).any():
            maxsat_logical_errors += 1

        # BP+OSD decode
        bposd_corr, _ = bposd_decoder.solve(syndrome)
        bposd_arr = np.array(bposd_corr, dtype=np.int8)
        bposd_residual = (error + bposd_arr) % 2
        if (L @ bposd_residual % 2).any():
            bposd_logical_errors += 1

    return {
        "error_rate": error_rate,
        "num_trials": num_trials,
        "maxsat_logical_error_rate": maxsat_logical_errors / num_trials,
        "maxsat_num_logical_errors": maxsat_logical_errors,
        "bposd_logical_error_rate": bposd_logical_errors / num_trials,
        "bposd_num_logical_errors": bposd_logical_errors,
    }


def main():
    # Load tasks
    with open("/app/tasks.json") as f:
        tasks = json.load(f)

    results = {"code_params": {}, "decoding_results": {}, "simulation_results": {}}

    # ── Parse hamming15 code from stabilizer generators ──
    print("Parsing hamming15.stab...")
    n, Hx, Hz = parse_stabilizer_file("/app/codes/hamming15.stab")
    print(f"  n={n}, Hx shape={Hx.shape}, Hz shape={Hz.shape}")

    # Compute logical operators
    Lx, Lz = compute_logical_operators(Hx, Hz, n)
    rx = gf2_rank(Hx)
    rz = gf2_rank(Hz)
    k = n - rx - rz
    print(f"  k={k}, Lx shape={Lx.shape}, Lz shape={Lz.shape}")

    # Verify normalization
    overlap = Lx @ Lz.T % 2
    print(f"  Lx @ Lz^T = I_k: {np.array_equal(overlap, np.eye(k, dtype=np.int8))}")

    # Compute distance
    d = compute_distance(Hx, Hz, n)
    print(f"  d={d}")

    results["code_params"]["hamming15"] = {
        "n": int(n),
        "k": int(k),
        "d": int(d),
        "Hx": Hx.tolist(),
        "Hz": Hz.tolist(),
        "Lx": Lx.tolist(),
        "Lz": Lz.tolist(),
    }

    # Build hamming15 code data dict for decoding functions
    hamming15_data = {
        "n": n,
        "k": k,
        "d": d,
        "Hx": Hx.tolist(),
        "Hz": Hz.tolist(),
        "Lx": Lx.tolist(),
        "Lz": Lz.tolist(),
    }

    # ── Build code cache ──
    code_cache = {"hamming15": hamming15_data}

    # ── Build decoders per (code, error_type) ──
    decoder_cache = {}

    def get_decoders(code_name, error_type):
        key = (code_name, error_type)
        if key not in decoder_cache:
            if code_name not in code_cache:
                code_cache[code_name] = load_code(code_name)
            code_data = code_cache[code_name]
            H = get_check_matrix(code_data, error_type)

            maxsat = LightsOutDecoder(H.tolist())
            maxsat.preconstruct()

            bposd = BpOsdDecoderWrapper(H.tolist(), error_rate=0.05)

            decoder_cache[key] = (maxsat, bposd)
        return decoder_cache[key]

    # ── Process decoding tasks ──
    print("\nDecoding tasks:")
    for task in tasks["decoding_tasks"]:
        code_name = task["code"]
        if code_name not in code_cache:
            code_cache[code_name] = load_code(code_name)
        code_data = code_cache[code_name]

        maxsat_dec, bposd_dec = get_decoders(code_name, task["error_type"])
        result = decode_single(task, code_data, maxsat_dec, bposd_dec)
        results["decoding_results"][task["id"]] = result

        ms = result["maxsat"]
        print(
            f"  {task['id']}: maxsat w={ms['weight']} logical={ms['is_logical_error']}"
        )
        if "bposd" in result:
            bp = result["bposd"]
            print(
                f"    bposd w={bp['weight']} logical={bp['is_logical_error']}"
            )

    # ── Process simulation tasks ──
    print("\nSimulation tasks:")
    for task in tasks["simulation_tasks"]:
        code_name = task["code"]
        if code_name not in code_cache:
            code_cache[code_name] = load_code(code_name)
        code_data = code_cache[code_name]

        maxsat_dec, bposd_dec = get_decoders(code_name, task["error_type"])
        result = simulate_task(task, code_data, maxsat_dec, bposd_dec)
        results["simulation_results"][task["id"]] = result

        print(
            f"  {task['id']}: maxsat_rate={result['maxsat_logical_error_rate']:.4f} "
            f"bposd_rate={result['bposd_logical_error_rate']:.4f}"
        )

    # ── Write results ──
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
