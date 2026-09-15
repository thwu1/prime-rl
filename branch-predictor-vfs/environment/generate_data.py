#!/usr/bin/env python3
"""Generate branch predictor simulation data for design-space analysis task.

Creates per-trace simulation output files for 10 predictor configurations across
15 benchmark traces in 3 workload categories, plus trace metadata.
"""
import os
import math
import json

os.makedirs('/app/data', exist_ok=True)

P2_TO_EXEC_STAGES = 9

# Trace definitions: (name, category, instructions, branches, conditional_branches)
traces = [
    ('server_web',     'server',     50000000, 10000000, 7800000),
    ('server_db',      'server',     50000000,  9500000, 7400000),
    ('server_cache',   'server',     50000000, 10500000, 8200000),
    ('server_rpc',     'server',     50000000,  9000000, 7000000),
    ('server_auth',    'server',     50000000,  9800000, 7600000),
    ('client_browser', 'client',     50000000,  7500000, 5800000),
    ('client_office',  'client',     50000000,  7000000, 5400000),
    ('client_game',    'client',     50000000,  8000000, 6200000),
    ('client_media',   'client',     50000000,  6500000, 5000000),
    ('client_ide',     'client',     50000000,  7200000, 5600000),
    ('sci_physics',    'scientific', 50000000,  5500000, 4200000),
    ('sci_climate',    'scientific', 50000000,  5000000, 3800000),
    ('sci_genome',     'scientific', 50000000,  6000000, 4600000),
    ('sci_fluid',      'scientific', 50000000,  5200000, 4000000),
    ('sci_ml_train',   'scientific', 50000000,  5800000, 4400000),
]

# Within-class noise multipliers (index 0-4 within each category)
within_ipc = [0.96, 0.98, 1.00, 1.02, 1.04]
within_cpi = [1.06, 1.03, 1.00, 0.97, 0.94]
within_epi = [0.98, 0.99, 1.00, 1.01, 1.02]

# Predictor definitions:
# (name, p1_lat, p2_lat, base_ipc, base_cpi, base_epi,
#  server_ipc_adj, client_ipc_adj, sci_ipc_adj,
#  server_cpi_adj, client_cpi_adj, sci_cpi_adj)
predictor_defs = [
    ('always_taken',    0.33, 0.33, 5.0,  0.180,   50,
     0.95, 1.00, 1.05, 1.10, 1.00, 0.90),
    ('bimodal',         0.67, 1.00, 6.5,  0.080,  200,
     0.97, 1.00, 1.03, 1.05, 1.00, 0.95),
    ('gshare',          0.67, 1.67, 7.0,  0.050,  380,
     1.00, 1.00, 1.00, 1.00, 1.00, 1.00),
    ('gshare_long',     1.00, 2.00, 7.1,  0.043,  420,
     1.02, 1.00, 0.98, 0.95, 1.00, 1.05),
    ('perceptron',      0.33, 3.00, 6.4,  0.045,  700,
     0.96, 1.00, 1.04, 1.05, 1.00, 0.95),
    ('perceptron_fast', 0.67, 2.33, 6.9,  0.042,  580,
     0.94, 1.08, 0.98, 1.08, 0.90, 1.02),
    ('tage_small',      1.00, 2.33, 7.2,  0.032,  520,
     0.90, 1.16, 0.92, 1.12, 0.80, 1.10),
    ('tage_large',      1.00, 3.33, 7.6,  0.022, 1200,
     1.18, 0.92, 0.88, 0.76, 1.12, 1.20),
    ('tage_ahead',      1.67, 1.67, 7.4,  0.020,  850,
     0.82, 1.00, 1.25, 1.25, 1.00, 0.72),
    ('hybrid_tp',       1.33, 3.67, 7.7,  0.019, 1400,
     1.06, 1.00, 0.94, 0.88, 1.00, 1.12),
]

# Generate trace metadata with category assignments and weights
trace_meta = {
    'categories': {
        'server': {
            'traces': [t[0] for t in traces if t[1] == 'server'],
            'weight': 0.5,
            'description': 'Server and cloud workloads with high branch density'
        },
        'client': {
            'traces': [t[0] for t in traces if t[1] == 'client'],
            'weight': 0.3,
            'description': 'Client and desktop applications with mixed branch patterns'
        },
        'scientific': {
            'traces': [t[0] for t in traces if t[1] == 'scientific'],
            'weight': 0.2,
            'description': 'Scientific and HPC workloads with regular branch patterns'
        }
    }
}

with open('/app/traces.json', 'w') as f:
    json.dump(trace_meta, f, indent=2)

# Generate simulation output data
for pred_def in predictor_defs:
    name, p1_lat, p2_lat = pred_def[0], pred_def[1], pred_def[2]
    base_ipc, base_cpi, base_epi = pred_def[3], pred_def[4], pred_def[5]
    s_ipc, c_ipc, sc_ipc = pred_def[6], pred_def[7], pred_def[8]
    s_cpi, c_cpi, sc_cpi = pred_def[9], pred_def[10], pred_def[11]

    pred_dir = f'/app/data/{name}'
    os.makedirs(pred_dir, exist_ok=True)

    p1_ceil = math.ceil(p1_lat)
    p2_ceil = math.ceil(p2_lat)
    cpi_factor = P2_TO_EXEC_STAGES + p2_ceil - max(1, min(p1_ceil, p2_ceil))

    cat_idx = {'server': 0, 'client': 0, 'scientific': 0}

    for trace_name, category, instr, branches, cond_br in traces:
        j = cat_idx[category]
        cat_idx[category] += 1

        if category == 'server':
            ipc_adj, cpi_adj = s_ipc, s_cpi
        elif category == 'client':
            ipc_adj, cpi_adj = c_ipc, c_cpi
        else:
            ipc_adj, cpi_adj = sc_ipc, sc_cpi

        target_ipc = base_ipc * ipc_adj * within_ipc[j]
        target_cpi = base_cpi * cpi_adj * within_cpi[j]
        target_epi = int(round(base_epi * within_epi[j]))

        mpi = target_cpi / cpi_factor
        misps = int(round(mpi * instr))
        target_cycles = instr / target_ipc

        if p2_ceil <= p1_ceil:
            effective_lat = max(1, p2_ceil) + 0.01
            npred = int(round(target_cycles / effective_lat))
            extra = int(round(npred * 0.01))
            diverge = 0
            div_at_end = 0
        else:
            diverge = misps * 2
            div_at_end = int(round(diverge * 0.3))
            non_npred_cycles = diverge * p2_ceil - div_at_end * max(1, p1_ceil)
            effective_lat = max(1, p1_ceil) + 0.02
            npred = int(round((target_cycles - non_npred_cycles) / effective_lat))
            extra = int(round(npred * 0.02))

        assert npred > 0, f"npred={npred} for {name}/{trace_name}"

        line = (f"{trace_name},{instr},{branches},{cond_br},{npred},{extra},"
                f"{diverge},{div_at_end},{misps},{p1_lat},{p2_lat},{target_epi}")
        with open(f'{pred_dir}/{trace_name}.out', 'w') as f:
            f.write(line + '\n')

print("Data generation complete: 10 predictors x 15 traces")
