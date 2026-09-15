#!/usr/bin/env python3
"""
Stockfish NNUE Network Binary Parser and Modifier

Parses the custom NNUE binary format by studying the Stockfish source code,
extracts metadata and parameters, creates a modified network with shifted biases,
and verifies the modification via UCI protocol interaction.

Binary format (determined from Stockfish source):
  1. Header: version(u32 LE) + hash(u32 LE) + desc_size(u32 LE) + description(bytes)
  2. Feature Transformer section hash (u32 LE)
  3. FT params (in order from read_parameters in nnue_feature_transformer.h):
     a. biases: COMPRESSED_LEB128 block (magic + byte_count + signed LEB128 int16[L1])
     b. threatWeights: LE int8[ThreatInputDims * L1]
     c. threatPsqtWeights: COMPRESSED_LEB128 block
     d. weights: COMPRESSED_LEB128 block
     e. psqtWeights: COMPRESSED_LEB128 block
  4. For each of 8 LayerStacks:
     - Architecture section hash (u32 LE)
     - fc_0, ac_0, fc_1, ac_1, fc_2 parameters

  Each COMPRESSED_LEB128 block (from nnue_common.h) consists of:
     "COMPRESSED_LEB128" (17 bytes magic) + byte_count (u32 LE) + LEB128 data

  The architecture hash in the header is based on layer dimensions (not parameter
  values), so modifying biases does not invalidate the hash.
"""

import struct
import json
import glob
import io
import os
import re
import subprocess
import time

LEB128_MAGIC = b"COMPRESSED_LEB128"
LEB128_MAGIC_SIZE = len(LEB128_MAGIC)  # 17


def find_nnue_file():
    """Determine the NNUE network filename from evaluate.h and locate it."""
    eval_h = "/app/Stockfish/src/evaluate.h"
    if os.path.exists(eval_h):
        with open(eval_h) as f:
            for line in f:
                m = re.search(r'EvalFileDefaultName\s+"([^"]+)"', line)
                if m:
                    path = f"/app/{m.group(1)}"
                    if os.path.exists(path):
                        return path
    candidates = sorted(glob.glob("/app/nn-*.nnue"))
    if candidates:
        return candidates[0]
    raise FileNotFoundError("No NNUE network file found in /app/")


def read_architecture_constants():
    """Extract L1, L2, L3, PSQTBuckets, LayerStacks from source code."""
    arch_h = "/app/Stockfish/src/nnue/nnue_architecture.h"
    constants = {}
    with open(arch_h) as f:
        content = f.read()
    patterns = {
        "L1": r'constexpr\s+IndexType\s+L1\s*=\s*(\d+)',
        "L2": r'constexpr\s+int\s+L2\s*=\s*(\d+)',
        "L3": r'constexpr\s+int\s+L3\s*=\s*(\d+)',
        "PSQTBuckets": r'constexpr\s+IndexType\s+PSQTBuckets\s*=\s*(\d+)',
        "LayerStacks": r'constexpr\s+IndexType\s+LayerStacks\s*=\s*(\d+)',
    }
    for name, pat in patterns.items():
        m = re.search(pat, content)
        if m:
            constants[name] = int(m.group(1))
        else:
            raise ValueError(f"Could not find constant {name} in {arch_h}")
    return constants


def read_signed_leb128(stream):
    """Decode a single signed LEB128 value from a binary stream."""
    result = 0
    shift = 0
    byte = 0
    while True:
        byte_data = stream.read(1)
        if not byte_data:
            raise EOFError("Unexpected end of stream in LEB128 decoding")
        byte = byte_data[0]
        result |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            break
    if byte & 0x40:
        result |= -(1 << shift)
    return result


def write_signed_leb128(value):
    """Encode a single signed integer as LEB128 bytes."""
    result = bytearray()
    more = True
    while more:
        byte = value & 0x7F
        value >>= 7
        if (value == 0 and not (byte & 0x40)) or (value == -1 and (byte & 0x40)):
            more = False
        else:
            byte |= 0x80
        result.append(byte)
    return bytes(result)


def run_stockfish_eval(extra_commands=""):
    """Run Stockfish and extract depth-1 eval using Popen for reliable I/O.

    Sends isready after setoption to ensure the network is loaded before searching.
    Reads and waits for readyok synchronization before issuing search commands.
    """
    proc = subprocess.Popen(
        ['/app/stockfish'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Phase 1: Set options and wait for readyok
    phase1 = ""
    if extra_commands:
        phase1 += extra_commands.rstrip('\n') + '\n'
    phase1 += "isready\n"
    proc.stdin.write(phase1)
    proc.stdin.flush()

    deadline = time.time() + 15
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if "readyok" in line:
            break

    # Phase 2: Search
    proc.stdin.write("ucinewgame\nisready\n")
    proc.stdin.flush()

    deadline = time.time() + 15
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if "readyok" in line:
            break

    proc.stdin.write("position startpos moves e2e4\ngo depth 1\n")
    proc.stdin.flush()

    score = None
    deadline = time.time() + 15
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        m = re.search(r"score cp (-?\d+)", line)
        if m:
            score = int(m.group(1))
        if "bestmove" in line:
            break

    try:
        proc.stdin.write("quit\n")
        proc.stdin.flush()
    except (BrokenPipeError, OSError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    return score


def main():
    nnue_path = find_nnue_file()
    print(f"[*] Parsing NNUE file: {nnue_path}")

    constants = read_architecture_constants()
    L1 = constants["L1"]
    L2 = constants["L2"]
    L3 = constants["L3"]
    psqt_buckets = constants["PSQTBuckets"]
    layer_stacks = constants["LayerStacks"]
    print(f"[*] Architecture: L1={L1}, L2={L2}, L3={L3}, "
          f"PSQTBuckets={psqt_buckets}, LayerStacks={layer_stacks}")

    with open(nnue_path, "rb") as f:
        raw_data = f.read()
    print(f"[*] File size: {len(raw_data)} bytes")

    # --- Parse header ---
    offset = 0
    version = struct.unpack_from("<I", raw_data, offset)[0]
    offset += 4
    hash_val = struct.unpack_from("<I", raw_data, offset)[0]
    offset += 4
    desc_size = struct.unpack_from("<I", raw_data, offset)[0]
    offset += 4
    description = raw_data[offset:offset + desc_size].decode("ascii", errors="replace")
    offset += desc_size

    print(f"[*] Version: {version}")
    print(f"[*] Hash: 0x{hash_val:08X}")
    print(f"[*] Description ({desc_size} bytes): {description[:80]}...")

    # --- Feature transformer section hash ---
    ft_hash = struct.unpack_from("<I", raw_data, offset)[0]
    offset += 4
    print(f"[*] FT section hash: 0x{ft_hash:08X}")

    # --- Read COMPRESSED_LEB128 block for biases ---
    # Each LEB128 section in Stockfish is prefixed with:
    #   "COMPRESSED_LEB128" (17 bytes magic string)
    #   byte_count (u32 LE) — total number of LEB128-encoded bytes
    bias_block_start = offset
    magic = raw_data[offset:offset + LEB128_MAGIC_SIZE]
    assert magic == LEB128_MAGIC, f"Expected LEB128 magic at offset {offset}, got {magic!r}"
    offset += LEB128_MAGIC_SIZE

    bias_leb_byte_count = struct.unpack_from("<I", raw_data, offset)[0]
    offset += 4

    print(f"[*] Bias LEB128 block: magic at {bias_block_start}, "
          f"byte_count={bias_leb_byte_count}, data at {offset}")

    # Decode biases from the LEB128 data
    leb_data = raw_data[offset:offset + bias_leb_byte_count]
    stream = io.BytesIO(leb_data)
    biases = []
    for _ in range(L1):
        biases.append(read_signed_leb128(stream))

    bytes_consumed = stream.tell()
    assert bytes_consumed == bias_leb_byte_count, \
        f"LEB128 decode consumed {bytes_consumed} bytes, expected {bias_leb_byte_count}"

    offset += bias_leb_byte_count
    bias_block_end = offset

    bias_sum = sum(biases)
    print(f"[*] Biases decoded: count={len(biases)}, sum={bias_sum}")
    print(f"[*] First 10 biases: {biases[:10]}")
    print(f"[*] Bias block: bytes {bias_block_start}-{bias_block_end} "
          f"({bias_block_end - bias_block_start} bytes total, "
          f"{bias_leb_byte_count} bytes LEB128 data)")

    # --- Create modified biases (add +10 to each) ---
    modified_biases = [b + 10 for b in biases]
    modified_leb_data = b""
    for b in modified_biases:
        modified_leb_data += write_signed_leb128(b)

    new_bias_leb_byte_count = len(modified_leb_data)
    print(f"[*] Modified LEB128 data: {new_bias_leb_byte_count} bytes "
          f"(original: {bias_leb_byte_count} bytes)")

    # --- Assemble modified NNUE file ---
    # Reconstruct the COMPRESSED_LEB128 block with updated byte count
    new_bias_block = (
        LEB128_MAGIC
        + struct.pack("<I", new_bias_leb_byte_count)
        + modified_leb_data
    )

    modified_data = (
        raw_data[:bias_block_start]   # header + FT hash (unchanged)
        + new_bias_block               # new COMPRESSED_LEB128 block for biases
        + raw_data[bias_block_end:]    # rest of file (unchanged)
    )

    modified_path = "/app/modified.nnue"
    with open(modified_path, "wb") as f:
        f.write(modified_data)
    print(f"[*] Modified network written: {modified_path} ({len(modified_data)} bytes)")

    # --- Write analysis.json ---
    analysis = {
        "description": description,
        "hash": f"0x{hash_val:08X}",
        "version": version,
        "ft_output_dim": L1,
        "ft_bias_count": L1,
        "ft_bias_sum": bias_sum,
        "layer_stacks": layer_stacks,
        "psqt_buckets": psqt_buckets,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print("[*] Analysis written to /app/analysis.json")

    # --- Verify modified network loads in Stockfish ---
    print("\n[*] Verifying modified network in Stockfish...")

    orig_score = run_stockfish_eval()
    mod_score = run_stockfish_eval(
        "setoption name EvalFile value /app/modified.nnue"
    )

    print(f"[*] Original eval (after 1.e4, depth 1): {orig_score} cp")
    print(f"[*] Modified eval (after 1.e4, depth 1): {mod_score} cp")

    if orig_score is not None and mod_score is not None and orig_score != mod_score:
        print("[+] Evaluations differ - modification successful!")
    else:
        print("[-] Warning: evaluations may not differ as expected")

    print("\n[+] Done.")


if __name__ == "__main__":
    main()
