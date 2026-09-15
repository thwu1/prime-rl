#!/usr/bin/env python3
"""Generate quantized model data for the mixed-storage forensics task.

"""
import numpy as np
import struct
import os
import sqlite3
import json
import subprocess

SEED = 42
BITS = 4
QMAX = (1 << BITS) - 1  # 15

# Secret mapping (NOT documented anywhere):
#   packing_mode 0 -> Method B (even-odd interleaved)
#   packing_mode 1 -> Method A (sequential)
#   packing_mode 2 -> Method C (bit-plane transposed)

LAYERS = [
    {"in_features": 128, "out_features": 256, "group_size": 64,
     "packing_mode": 2, "scale_dtype": "float16", "container": "raw",
     "activation": "relu"},
    {"in_features": 256, "out_features": 192, "group_size": 32,
     "packing_mode": 0, "scale_dtype": "float32", "container": "elf",
     "activation": "gelu"},
    {"in_features": 192, "out_features": 128, "group_size": 64,
     "packing_mode": 1, "scale_dtype": "float32", "container": "raw",
     "activation": "relu"},
    {"in_features": 128, "out_features": 64, "group_size": 32,
     "packing_mode": 2, "scale_dtype": "float16", "container": "raw",
     "activation": "none"},
]

CORRUPT_LAYER = 1
CORRUPT_GROUP = 2

TEST_SEEDS = [100, 200, 300, 400, 500]


def gelu_approx(x):
    """GELU tanh approximation, computed in float64 for consistency."""
    x64 = x.astype(np.float64)
    result = 0.5 * x64 * (1.0 + np.tanh(
        np.sqrt(2.0 / np.pi) * (x64 + 0.044715 * x64 ** 3)))
    return result.astype(np.float32)


ACTIVATIONS = {
    "relu": lambda x: np.maximum(x, np.float32(0.0)),
    "gelu": gelu_approx,
    "none": lambda x: x,
}


def quantize_group(values):
    """Asymmetric INT4 quantization of a group of float32 values."""
    min_val = float(values.min())
    max_val = float(values.max())
    if max_val - min_val < 1e-10:
        return np.zeros(len(values), dtype=np.int32), np.float32(1.0), 0
    scale = np.float32((max_val - min_val) / QMAX)
    zp = int(np.clip(round(-min_val / float(scale)), 0, QMAX))
    q = np.clip(
        np.round(values.astype(np.float32) / float(scale) + zp), 0, QMAX
    ).astype(np.int32)
    return q, scale, zp


def pack_sequential(vals, count=8):
    """Method A: v0 at [3:0], v1 at [7:4], ..., v7 at [31:28]."""
    p = 0
    for i in range(count):
        p |= (int(vals[i]) & 0xF) << (i * 4)
    return p


def pack_interleaved(vals, count=8):
    """Method B: even indices in lower 16 bits, odd in upper 16 bits."""
    p = 0
    for i, idx in enumerate([0, 2, 4, 6]):
        p |= (int(vals[idx]) & 0xF) << (i * 4)
    for i, idx in enumerate([1, 3, 5, 7]):
        p |= (int(vals[idx]) & 0xF) << (16 + i * 4)
    return p


def pack_bitplane(vals, count=8):
    """Method C: bit-plane transposed."""
    p = 0
    for bit in range(4):
        for vi in range(8):
            if int(vals[vi]) & (1 << bit):
                p |= 1 << (bit * 8 + vi)
    return p


MODE_TO_PACK = {
    0: pack_interleaved,
    1: pack_sequential,
    2: pack_bitplane,
}


def create_database(db_path, layers_config, correct_scales_for_corrupt):
    """Create SQLite database with model configuration and calibration data."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Model-level configuration
    c.execute('''CREATE TABLE model_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    c.execute("INSERT INTO model_config VALUES ('num_layers', ?)",
              (str(len(layers_config)),))
    c.execute("INSERT INTO model_config VALUES ('input_dim', '128')")
    c.execute("INSERT INTO model_config VALUES ('output_dim', '64')")
    c.execute("INSERT INTO model_config VALUES ('quantization_bits', '4')")
    c.execute("INSERT INTO model_config VALUES ('format_version', '1.1')")

    # Per-layer configuration
    c.execute('''CREATE TABLE layer_config (
        layer_id INTEGER PRIMARY KEY,
        in_features INTEGER NOT NULL,
        out_features INTEGER NOT NULL,
        group_size INTEGER NOT NULL,
        packing_mode INTEGER NOT NULL,
        scale_dtype TEXT NOT NULL,
        weight_container TEXT NOT NULL,
        activation TEXT NOT NULL,
        notes TEXT
    )''')

    for i, lc in enumerate(layers_config):
        notes = None
        if lc['container'] == 'elf':
            notes = ('Weights embedded in ELF relocatable object: '
                     'section .quantized_weights')
        c.execute(
            "INSERT INTO layer_config VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (i, lc['in_features'], lc['out_features'], lc['group_size'],
             lc['packing_mode'], lc['scale_dtype'], lc['container'],
             lc['activation'], notes)
        )

    # Calibration notes (mix of info and critical entries)
    c.execute('''CREATE TABLE calibration_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        layer_id INTEGER NOT NULL,
        group_idx INTEGER,
        severity TEXT NOT NULL,
        note TEXT NOT NULL
    )''')

    c.execute(
        "INSERT INTO calibration_notes (layer_id, group_idx, severity, note) "
        "VALUES (?, ?, ?, ?)",
        (0, None, 'info',
         'Calibration completed successfully. No issues detected.'))
    c.execute(
        "INSERT INTO calibration_notes (layer_id, group_idx, severity, note) "
        "VALUES (?, ?, ?, ?)",
        (1, None, 'info',
         'Layer weights exported in ELF container format for '
         'toolchain compatibility.'))
    c.execute(
        "INSERT INTO calibration_notes (layer_id, group_idx, severity, note) "
        "VALUES (?, ?, ?, ?)",
        (1, CORRUPT_GROUP, 'critical',
         'Scale overflow detected during FP32 export for group %d. '
         'All scale values for this group were zeroed as a safety measure. '
         'Corrected per-row scale factors stored in scale_corrections table.'
         % CORRUPT_GROUP))
    c.execute(
        "INSERT INTO calibration_notes (layer_id, group_idx, severity, note) "
        "VALUES (?, ?, ?, ?)",
        (2, None, 'info',
         'Calibration completed successfully. No issues detected.'))
    c.execute(
        "INSERT INTO calibration_notes (layer_id, group_idx, severity, note) "
        "VALUES (?, ?, ?, ?)",
        (3, None, 'info',
         'Calibration completed successfully. No issues detected.'))

    # Scale corrections table (corrected values for the corrupted group)
    c.execute('''CREATE TABLE scale_corrections (
        layer_id INTEGER NOT NULL,
        group_idx INTEGER NOT NULL,
        row_idx INTEGER NOT NULL,
        corrected_scale REAL NOT NULL,
        PRIMARY KEY (layer_id, group_idx, row_idx)
    )''')

    nr = layers_config[CORRUPT_LAYER]['out_features']
    for row in range(nr):
        c.execute(
            "INSERT INTO scale_corrections VALUES (?, ?, ?, ?)",
            (CORRUPT_LAYER, CORRUPT_GROUP, row,
             float(correct_scales_for_corrupt[row]))
        )

    conn.commit()
    conn.close()


def main():
    rng = np.random.RandomState(SEED)
    os.makedirs('/app/model', exist_ok=True)
    os.makedirs('/app/reference', exist_ok=True)
    os.makedirs('/app/known_weights', exist_ok=True)

    dequant_weights = []
    known = {}
    all_correct_scales = {}

    for li, lc in enumerate(LAYERS):
        nr = lc['out_features']
        nc = lc['in_features']
        gs = lc['group_size']
        ng = nc // gs
        pm = lc['packing_mode']
        sd = lc['scale_dtype']
        pack_fn = MODE_TO_PACK[pm]

        # Generate random weights
        W = (rng.randn(nr, nc) * 0.1).astype(np.float32)

        # Quantize per group
        q_w = np.zeros((nr, nc), dtype=np.int32)
        scales = np.zeros((nr, ng), dtype=np.float32)
        zeros = np.zeros((nr, ng), dtype=np.int32)

        for r in range(nr):
            for g in range(ng):
                s, e = g * gs, (g + 1) * gs
                q, sc, zp = quantize_group(W[r, s:e])
                q_w[r, s:e] = q
                scales[r, g] = sc
                zeros[r, g] = zp

        # Compute actual scales (with dtype precision)
        if sd == "float16":
            actual_scales = scales.astype(np.float16).astype(np.float32)
        else:
            actual_scales = scales.copy()

        all_correct_scales[li] = actual_scales.copy()

        # Pack weights
        ppr = nc // 8
        packed_w = []
        for r in range(nr):
            for p in range(ppr):
                packed_w.append(pack_fn(q_w[r, p * 8:(p + 1) * 8]))

        # Pack zero-points (always sequential, regardless of packing_mode)
        zppr = (ng + 7) // 8
        packed_z = []
        for r in range(nr):
            for pi in range(zppr):
                s2 = pi * 8
                cnt = min(8, ng - s2)
                packed_z.append(pack_sequential(zeros[r, s2:s2 + cnt], cnt))

        # Build raw weight binary data
        weight_data = struct.pack('<III', nr, nc, gs)
        for v in packed_w:
            weight_data += struct.pack('<I', v & 0xFFFFFFFF)

        # Store in appropriate container
        if lc['container'] == 'elf':
            raw_path = '/tmp/layer_raw.bin'
            with open(raw_path, 'wb') as f:
                f.write(weight_data)
            elf_path = '/app/model/layer_%d.o' % li
            subprocess.run([
                'objcopy', '-I', 'binary', '-O', 'elf64-x86-64',
                '--rename-section', '.data=.quantized_weights',
                raw_path, elf_path
            ], check=True)
            os.remove(raw_path)
        else:
            with open('/app/model/layer_%d.qweight' % li, 'wb') as f:
                f.write(weight_data)

        # Write scale factors (corrupt target layer/group)
        write_scales = actual_scales.copy()
        if li == CORRUPT_LAYER:
            write_scales[:, CORRUPT_GROUP] = 0.0

        with open('/app/model/layer_%d.scales' % li, 'wb') as f:
            f.write(struct.pack('<II', nr, ng))
            if sd == "float32":
                f.write(write_scales.astype(np.float32).tobytes())
            else:
                f.write(write_scales.astype(np.float16).tobytes())

        # Write zero-points
        with open('/app/model/layer_%d.zeros' % li, 'wb') as f:
            f.write(struct.pack('<II', nr, ng))
            for v in packed_z:
                f.write(struct.pack('<I', v & 0xFFFFFFFF))

        # Dequantize for reference using CORRECT scales
        se = np.repeat(actual_scales, gs, axis=1)
        ze = np.repeat(zeros, gs, axis=1)
        dW = se * (q_w.astype(np.float32) - ze.astype(np.float32))
        dequant_weights.append(dW)

        # Known weights for forensic analysis
        ncols = min(16, nc)
        known['layer_%d' % li] = {
            "description": "Row 0, columns 0-%d of layer %d" % (ncols - 1, li),
            "packing_mode": pm,
            "quantized_int4_values": q_w[0, :ncols].tolist(),
            "dequantized_float_values": [
                round(float(v), 8) for v in dW[0, :ncols]],
        }

    with open('/app/known_weights/reference_values.json', 'w') as f:
        json.dump(known, f, indent=2)

    # Create SQLite database with model config and calibration corrections
    correct_corrupt_scales = all_correct_scales[CORRUPT_LAYER][:, CORRUPT_GROUP]
    create_database('/app/model/calibration.db', LAYERS,
                    correct_corrupt_scales)

    # Generate reference input/output pairs
    for t, seed in enumerate(TEST_SEEDS):
        trng = np.random.RandomState(seed)
        x = (trng.randn(1, LAYERS[0]['in_features']) * 0.5).astype(np.float32)
        np.save('/app/reference/input_%d.npy' % t, x)

        cur = x.copy()
        for i, dW in enumerate(dequant_weights):
            cur = cur @ dW.T
            act_fn = ACTIVATIONS[LAYERS[i]['activation']]
            cur = act_fn(cur)
        np.save('/app/reference/output_%d.npy' % t, cur.astype(np.float32))

    print("Data generation complete.")
    for i, l in enumerate(LAYERS):
        print("  Layer %d: %dx%d, gs=%d, mode=%d, scale=%s, "
              "container=%s, act=%s" % (
                  i, l['out_features'], l['in_features'],
                  l['group_size'], l['packing_mode'], l['scale_dtype'],
                  l['container'], l['activation']))


if __name__ == '__main__':
    main()
