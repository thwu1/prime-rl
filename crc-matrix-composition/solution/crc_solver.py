#!/usr/bin/env python3
"""Solution: Hardware CRC module using Amaranth HDL.

"""

import json
import os

from amaranth import *
from amaranth.lib.crc import Algorithm
from amaranth.sim import Simulator


def _make_params(spec):
    """Create Amaranth CRC Parameters from a spec dict."""
    algo = Algorithm(
        crc_width=spec["crc_width"],
        polynomial=spec["polynomial"],
        initial_crc=spec["initial_crc"],
        reflect_input=spec["reflect_input"],
        reflect_output=spec["reflect_output"],
        xor_output=spec["xor_output"],
    )
    return algo(spec["data_width"])


class CRCProcessor(Elaboratable):
    """Hardware CRC processor wrapping Amaranth's built-in CRC Processor."""

    def __init__(self, spec):
        self._spec = spec
        params = _make_params(spec)
        self._inner = params.create()
        self.start = self._inner.start
        self.data = self._inner.data
        self.valid = self._inner.valid
        self.crc = self._inner.crc
        self.match_detected = self._inner.match_detected
        self._matrix_f = self._inner._matrix_f
        self._matrix_g = self._inner._matrix_g

    def elaborate(self, platform):
        m = Module()
        m.submodules.crc_core = self._inner
        return m


def _reflect(word, n):
    """Bit-reflect an n-bit word."""
    return int(f"{word:0{n}b}"[::-1], 2)


def _gf2_mat_mul(a, b, n):
    """Multiply two n x n matrices over GF(2)."""
    c = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            v = 0
            for k in range(n):
                v ^= a[i][k] & b[k][j]
            c[i][j] = v
    return c


def _gf2_mat_pow(mat, exp, n):
    """Compute mat^exp for n x n matrix over GF(2)."""
    result = [[1 if i == j else 0 for j in range(n)] for i in range(n)]
    base = [row[:] for row in mat]
    while exp > 0:
        if exp & 1:
            result = _gf2_mat_mul(result, base, n)
        base = _gf2_mat_mul(base, base, n)
        exp >>= 1
    return result


def compose_crc(crc_a, data_b, spec):
    """Compose CRC: return CRC(A||B) given CRC(A) and data B."""
    if not data_b:
        return crc_a

    crc_width = spec["crc_width"]
    reflect_output = spec["reflect_output"]
    xor_output = spec["xor_output"]

    # Recover raw register state from output CRC of A
    undone = crc_a ^ xor_output
    if reflect_output:
        raw_a = _reflect(undone, crc_width)
    else:
        raw_a = undone

    # Compute raw CRC of B from zero initial state (no output processing)
    raw_algo = Algorithm(
        crc_width=spec["crc_width"],
        polynomial=spec["polynomial"],
        initial_crc=0,
        reflect_input=spec["reflect_input"],
        reflect_output=False,
        xor_output=0,
    )
    raw_b = raw_algo(spec["data_width"]).compute(data_b)

    # Get F matrix and compute F^len(B)
    params = _make_params(spec)
    f_matrix, _ = params._matrices()
    f_power = _gf2_mat_pow(f_matrix, len(data_b), crc_width)

    # Apply F^len(B) to raw_a using transposed convention:
    # output[i] = XOR_j(f_power[j][i] * raw_a_bits[j])
    raw_a_bits = [(raw_a >> i) & 1 for i in range(crc_width)]
    advanced_bits = [0] * crc_width
    for i in range(crc_width):
        v = 0
        for j in range(crc_width):
            v ^= f_power[j][i] & raw_a_bits[j]
        advanced_bits[i] = v
    advanced = sum(b << i for i, b in enumerate(advanced_bits))

    # Combine and apply output processing
    final_raw = advanced ^ raw_b
    if reflect_output:
        result = _reflect(final_raw, crc_width)
    else:
        result = final_raw
    return result ^ xor_output


def compute_residue(spec):
    """Compute the CRC residue value."""
    params = _make_params(spec)
    return params.residue()


def _resolve_data(tv):
    """Resolve test vector to list of data bytes."""
    if "data_hex" in tv:
        return list(bytes.fromhex(tv["data_hex"]))
    gen = tv.get("generate", "")
    if gen == "range_256":
        return list(range(256))
    elif gen == "repeat_0xAA_128":
        return [0xAA] * 128
    raise ValueError(f"Unknown test vector format: {tv}")


def main():
    """Simulate CRCProcessor, compute all outputs, write to /app/output/."""
    with open("/app/spec.json") as f:
        raw_spec = json.load(f)

    spec = {
        "crc_width": raw_spec["crc_width"],
        "polynomial": int(raw_spec["polynomial"], 16),
        "initial_crc": int(raw_spec["initial_crc"], 16),
        "reflect_input": raw_spec["reflect_input"],
        "reflect_output": raw_spec["reflect_output"],
        "xor_output": int(raw_spec["xor_output"], 16),
        "data_width": raw_spec["data_width"],
    }

    # Resolve all test vector data
    tv_data = {}
    for tv in raw_spec["test_vectors"]:
        tv_data[tv["id"]] = _resolve_data(tv)

    # Build hardware processor
    proc = CRCProcessor(spec)
    crc_values = {}

    # Simulate all test vectors through hardware
    sim = Simulator(proc)
    sim.add_clock(1e-6)

    async def testbench(ctx):
        for tv in raw_spec["test_vectors"]:
            data = tv_data[tv["id"]]

            # Assert start with first data byte
            ctx.set(proc.start, 1)
            ctx.set(proc.data, data[0])
            ctx.set(proc.valid, 1)
            await ctx.tick()

            # Process remaining bytes
            ctx.set(proc.start, 0)
            for byte in data[1:]:
                ctx.set(proc.data, byte)
                await ctx.tick()

            # Read CRC output
            ctx.set(proc.valid, 0)
            await ctx.tick()
            crc_values[tv["id"]] = ctx.get(proc.crc)

    sim.add_testbench(testbench)

    os.makedirs("/app/output", exist_ok=True)
    with sim.write_vcd("/app/output/hw_simulation.vcd"):
        sim.run()

    # Extract internal matrices from the hardware processor
    f_matrix = proc._matrix_f
    g_matrix = proc._matrix_g

    # Compute composition results
    params = _make_params(spec)
    composed = {}
    for ct in raw_spec["composition_tests"]:
        full_data = tv_data[ct["data_source"]]
        split = ct["split_point"]
        crc_a = params.compute(full_data[:split])
        composed[ct["id"]] = compose_crc(crc_a, full_data[split:], spec)

    # Compute residue
    residue = compute_residue(spec)

    # Write all output files
    with open("/app/output/crc_values.json", "w") as f:
        json.dump(crc_values, f)
    with open("/app/output/f_matrix.json", "w") as f:
        json.dump(f_matrix, f)
    with open("/app/output/g_matrix.json", "w") as f:
        json.dump(g_matrix, f)
    with open("/app/output/composed_crcs.json", "w") as f:
        json.dump(composed, f)
    with open("/app/output/residue.txt", "w") as f:
        f.write(str(residue))

    print("All outputs written to /app/output/")


if __name__ == "__main__":
    main()
