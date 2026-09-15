#!/usr/bin/env python3
"""
Mixed-storage quantized model inference.
Handles SQLite configuration, ELF weight extraction, calibration corrections,
multiple packing modes, and mixed activation functions.

"""
import sys
import os
import struct
import sqlite3
import subprocess
import tempfile
import json
import numpy as np


# --- Three unpacking methods ---

def unpack_sequential(packed, nr, nc):
    """Method A: v0 at [3:0], ..., v7 at [31:28]."""
    packed = packed.reshape(nr, nc // 8).astype(np.uint64)
    q = np.zeros((nr, nc), dtype=np.int32)
    for j in range(8):
        q[:, j::8] = (packed >> (j * 4)) & 0xF
    return q


def unpack_interleaved(packed, nr, nc):
    """Method B: even in lower 16 bits, odd in upper 16 bits."""
    packed = packed.reshape(nr, nc // 8).astype(np.uint64)
    q = np.zeros((nr, nc), dtype=np.int32)
    for j in range(4):
        q[:, (2 * j)::8] = (packed >> (j * 4)) & 0xF
        q[:, (2 * j + 1)::8] = (packed >> (16 + j * 4)) & 0xF
    return q


def unpack_bitplane(packed, nr, nc):
    """Method C: bit-plane transposed."""
    packed = packed.reshape(nr, nc // 8).astype(np.uint64)
    q = np.zeros((nr, nc), dtype=np.int32)
    for bit in range(4):
        for vi in range(8):
            q[:, vi::8] |= (((packed >> (bit * 8 + vi)) & 1) << bit).astype(
                np.int32)
    return q


ALL_METHODS = [unpack_sequential, unpack_interleaved, unpack_bitplane]


# --- Activation functions ---

def gelu_approx(x):
    """GELU with tanh approximation."""
    x64 = x.astype(np.float64)
    result = 0.5 * x64 * (1.0 + np.tanh(
        np.sqrt(2.0 / np.pi) * (x64 + 0.044715 * x64 ** 3)))
    return result.astype(np.float32)


ACTIVATIONS = {
    "relu": lambda x: np.maximum(x, np.float32(0.0)),
    "gelu": gelu_approx,
    "none": lambda x: x,
}


def extract_elf_weights(elf_path, section_name):
    """Extract weight data from an ELF section using objcopy."""
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.run(
            ['objcopy', '--dump-section',
             '%s=%s' % (section_name, tmp_path), elf_path],
            check=True, capture_output=True
        )
        with open(tmp_path, 'rb') as f:
            return f.read()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def determine_mode_mapping(model_dir, layer_configs):
    """Determine packing_mode -> unpack function via known weight data."""
    known_path = os.path.join(
        os.path.dirname(os.path.abspath(model_dir)),
        'known_weights', 'reference_values.json')
    with open(known_path) as f:
        known = json.load(f)

    mapping = {}
    for lc in layer_configs:
        li = lc['layer_id']
        pm = lc['packing_mode']
        if pm in mapping:
            continue

        lk = known.get('layer_%d' % li)
        if lk is None:
            continue

        nr = lc['out_features']
        nc = lc['in_features']
        expected_q = np.array(lk['quantized_int4_values'], dtype=np.int32)

        # Load raw weight data from the appropriate container
        if lc['weight_container'] == 'elf':
            section = '.quantized_weights'
            if lc['notes'] and 'section' in lc['notes']:
                for part in lc['notes'].split():
                    if part.startswith('.'):
                        section = part
                        break
            raw_data = extract_elf_weights(
                os.path.join(model_dir, 'layer_%d.o' % li), section)
            struct.unpack('<III', raw_data[:12])
            raw = np.frombuffer(raw_data[12:], dtype=np.uint32).copy()
        else:
            with open(os.path.join(
                    model_dir, 'layer_%d.qweight' % li), 'rb') as f:
                struct.unpack('<III', f.read(12))
                raw = np.frombuffer(f.read(), dtype=np.uint32).copy()

        for method in ALL_METHODS:
            q = method(raw, nr, nc)
            if np.array_equal(q[0, :len(expected_q)], expected_q):
                mapping[pm] = method
                break

    return mapping


def main():
    if len(sys.argv) != 4:
        print("Usage: %s <model_dir> <input.npy> <output.npy>" % sys.argv[0])
        sys.exit(1)

    model_dir = sys.argv[1]
    input_path = sys.argv[2]
    output_path = sys.argv[3]

    # Load configuration from SQLite database
    db_path = os.path.join(model_dir, 'calibration.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    layer_configs = []
    for row in c.execute("SELECT * FROM layer_config ORDER BY layer_id"):
        layer_configs.append({
            'layer_id': row[0], 'in_features': row[1],
            'out_features': row[2], 'group_size': row[3],
            'packing_mode': row[4], 'scale_dtype': row[5],
            'weight_container': row[6], 'activation': row[7],
            'notes': row[8],
        })

    # Load scale corrections
    corrections = {}
    for row in c.execute(
            "SELECT layer_id, group_idx, row_idx, corrected_scale "
            "FROM scale_corrections"):
        key = (row[0], row[1])
        if key not in corrections:
            corrections[key] = {}
        corrections[key][row[2]] = row[3]

    conn.close()

    # Determine packing mode mapping empirically
    mode_map = determine_mode_mapping(model_dir, layer_configs)

    x = np.load(input_path).astype(np.float32)

    for lc in layer_configs:
        li = lc['layer_id']
        nr = lc['out_features']
        nc = lc['in_features']
        gs = lc['group_size']
        ng = nc // gs
        pm = lc['packing_mode']
        sd = lc['scale_dtype']

        # Load weight data from appropriate container
        if lc['weight_container'] == 'elf':
            section = '.quantized_weights'
            if lc['notes'] and 'section' in lc['notes']:
                for part in lc['notes'].split():
                    if part.startswith('.'):
                        section = part
                        break
            raw_data = extract_elf_weights(
                os.path.join(model_dir, 'layer_%d.o' % li), section)
            struct.unpack('<III', raw_data[:12])
            raw = np.frombuffer(raw_data[12:], dtype=np.uint32).copy()
        else:
            with open(os.path.join(
                    model_dir, 'layer_%d.qweight' % li), 'rb') as f:
                struct.unpack('<III', f.read(12))
                raw = np.frombuffer(f.read(), dtype=np.uint32).copy()

        q = mode_map[pm](raw, nr, nc)

        # Load scales
        with open(os.path.join(
                model_dir, 'layer_%d.scales' % li), 'rb') as f:
            struct.unpack('<II', f.read(8))
            if sd == 'float16':
                scales = np.frombuffer(
                    f.read(), dtype=np.float16
                ).copy().astype(np.float32).reshape(nr, ng)
            else:
                scales = np.frombuffer(
                    f.read(), dtype=np.float32
                ).copy().reshape(nr, ng)

        # Apply calibration corrections from database
        for (cl, cg), row_corr in corrections.items():
            if cl == li:
                for ri, cv in row_corr.items():
                    scales[ri, cg] = cv

        # Load zero-points (always sequential packing)
        with open(os.path.join(
                model_dir, 'layer_%d.zeros' % li), 'rb') as f:
            struct.unpack('<II', f.read(8))
            zppr = (ng + 7) // 8
            zraw = np.frombuffer(f.read(), dtype=np.uint32).copy()
        zp = zraw.reshape(nr, zppr).astype(np.uint64)
        zeros = np.zeros((nr, ng), dtype=np.int32)
        for j in range(ng):
            zeros[:, j] = (zp[:, j // 8] >> ((j % 8) * 4)) & 0xF

        # Dequantize
        se = np.repeat(scales, gs, axis=1)
        ze = np.repeat(zeros, gs, axis=1)
        W = se * (q.astype(np.float32) - ze.astype(np.float32))

        # Forward pass with per-layer activation
        x = x @ W.T
        act_fn = ACTIVATIONS[lc['activation']]
        x = act_fn(x)

    np.save(output_path, x)


if __name__ == '__main__':
    main()
