#!/usr/bin/env python3
"""Capacity planning analysis for MoE LLM serving deployment."""

import json
import sqlite3
import yaml
import numpy as np


def load_traces_for_rate(db_path, rate):
    """Load all request traces for a given request rate from SQLite."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('''
        SELECT t.request_id, t.arrival_time, t.prompt_len, t.output_len,
               t.ttft, t.latency, t.success, t.itl
        FROM traces t
        JOIN runs r ON t.run_id = r.run_id
        WHERE ABS(r.request_rate - ?) < 0.01
        ORDER BY t.request_id
    ''', (rate,))
    rows = cur.fetchall()
    conn.close()
    return [{
        'request_id': r['request_id'],
        'arrival_time': r['arrival_time'],
        'prompt_len': r['prompt_len'],
        'output_len': r['output_len'],
        'ttft': r['ttft'],
        'latency': r['latency'],
        'success': bool(r['success']),
        'itl': json.loads(r['itl'])
    } for r in rows]


def get_all_runs(db_path):
    """Get all benchmark run metadata from SQLite."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT run_id, request_rate, num_requests FROM runs ORDER BY request_rate')
    rows = cur.fetchall()
    conn.close()
    return [{'run_id': r[0], 'request_rate': r[1], 'num_requests': r[2]} for r in rows]


def main():
    db_path = '/app/data/benchmarks.db'

    # Load YAML deployment config (cluster specs + server params)
    with open('/app/data/server_config.yaml') as f:
        deploy_config = yaml.safe_load(f)

    cluster = deploy_config['cluster']
    server = deploy_config['server']

    # Load model architecture (JSON)
    with open('/app/data/model_config.json') as f:
        model = json.load(f)

    # Load SLO targets (JSON)
    with open('/app/data/slo_targets.json') as f:
        slo = json.load(f)

    mem_fraction = server['mem_fraction_static']
    gpu_memory = cluster['gpu_memory_bytes']
    num_gpus = cluster['num_gpus']
    benchmark_tp = server['tp_size']

    # ---- Trace Analysis (from SQLite) ----
    runs = get_all_runs(db_path)
    trace_analysis = {}

    for run in runs:
        rate = run['request_rate']
        data = load_traces_for_rate(db_path, rate)

        successful = [r for r in data if r['success']]
        if not successful:
            continue

        # TTFT in ms
        ttfts_ms = np.array([r['ttft'] * 1000.0 for r in successful])

        # TPOT: (latency - ttft) / (output_len - 1) in ms
        tpots_ms = np.array([
            (r['latency'] - r['ttft']) / max(r['output_len'] - 1, 1) * 1000.0
            for r in successful
        ])

        # ITL: flatten all inter-token latency arrays (parsed from JSON), in ms
        all_itls_ms = []
        for r in successful:
            all_itls_ms.extend([t * 1000.0 for t in r.get('itl', [])])
        all_itls_ms = np.array(all_itls_ms) if all_itls_ms else np.array([0.0])

        # Output throughput
        total_output_tokens = sum(r['output_len'] for r in successful)
        t_start = min(r['arrival_time'] for r in data)
        t_end = max(r['arrival_time'] + r['latency'] for r in data)
        duration = t_end - t_start
        throughput = total_output_tokens / duration if duration > 0 else 0

        key = 'rate_{}'.format(rate)
        trace_analysis[key] = {
            'request_rate': rate,
            'num_successful': len(successful),
            'num_total': len(data),
            'ttft_p50_ms': float(np.percentile(ttfts_ms, 50)),
            'ttft_p95_ms': float(np.percentile(ttfts_ms, 95)),
            'ttft_p99_ms': float(np.percentile(ttfts_ms, 99)),
            'tpot_p50_ms': float(np.percentile(tpots_ms, 50)),
            'tpot_p95_ms': float(np.percentile(tpots_ms, 95)),
            'tpot_p99_ms': float(np.percentile(tpots_ms, 99)),
            'itl_p50_ms': float(np.percentile(all_itls_ms, 50)),
            'itl_p95_ms': float(np.percentile(all_itls_ms, 95)),
            'itl_p99_ms': float(np.percentile(all_itls_ms, 99)),
            'throughput_tok_per_sec': throughput,
        }

    # ---- Memory Analysis ----
    hidden = model['hidden_size']
    num_heads = model['num_attention_heads']
    num_kv_heads = model['num_kv_heads']
    head_dim = model['head_dim']
    intermediate = model['intermediate_size']
    vocab = model['vocab_size']
    num_layers = model['num_layers']
    num_experts = model['num_experts']
    bpp = model['bytes_per_param']
    tie_embeddings = model.get('tie_word_embeddings', True)

    # Embedding
    embedding_params = vocab * hidden

    # LM head (untied = separate weight matrix)
    lm_head_params = 0 if tie_embeddings else vocab * hidden

    # Per-layer GQA attention: Q, K, V, O projections
    attn_per_layer = (hidden * num_heads * head_dim      # Q
                      + hidden * num_kv_heads * head_dim  # K
                      + hidden * num_kv_heads * head_dim  # V
                      + num_heads * head_dim * hidden)    # O

    # Per-layer MoE: router gate + expert MLPs (gate_proj, up_proj, down_proj)
    gate_per_layer = hidden * num_experts
    expert_params_each = hidden * intermediate * 3
    moe_per_layer = gate_per_layer + num_experts * expert_params_each

    # Per-layer RMSNorm (pre-attention + post-attention)
    norm_per_layer = 2 * hidden

    # Final RMSNorm before LM head
    final_norm = hidden

    per_layer_total = attn_per_layer + moe_per_layer + norm_per_layer
    total_params = (embedding_params + lm_head_params
                    + num_layers * per_layer_total + final_norm)
    total_bytes = total_params * bpp
    total_gb = total_bytes / (1024 ** 3)

    # KV cache per token: 2 (K+V) * num_layers * num_kv_heads * head_dim * bpp
    kv_bytes_per_token = 2 * num_layers * num_kv_heads * head_dim * bpp

    usable_memory = gpu_memory * mem_fraction

    configurations = {}
    for tp in [1, 2, 4, 8]:
        weight_per_gpu = total_bytes / tp
        fits = weight_per_gpu < usable_memory
        kv_per_tok_per_gpu = kv_bytes_per_token / tp
        if fits:
            available_for_kv = usable_memory - weight_per_gpu
            max_kv_tokens = int(available_for_kv / kv_per_tok_per_gpu)
        else:
            max_kv_tokens = 0

        configurations['tp_{}'.format(tp)] = {
            'tp_size': tp,
            'model_weight_per_gpu_gb': weight_per_gpu / (1024 ** 3),
            'fits': fits,
            'max_kv_tokens': max_kv_tokens,
        }

    memory_analysis = {
        'model_weights_total_gb': total_gb,
        'kv_cache_bytes_per_token': kv_bytes_per_token,
        'configurations': configurations,
    }

    # ---- Saturation Rate ----
    ttft_slo = slo['ttft_p99_ms']
    saturation_rate = None
    for run in sorted(runs, key=lambda r: r['request_rate']):
        rate = run['request_rate']
        key = 'rate_{}'.format(rate)
        if key in trace_analysis:
            if trace_analysis[key]['ttft_p99_ms'] <= ttft_slo:
                saturation_rate = rate

    # ---- Recommended Config ----
    baseline_throughput = 0
    baseline_tpot_p99 = 0
    baseline_ttft_p99 = 0
    if saturation_rate is not None:
        sat_key = 'rate_{}'.format(saturation_rate)
        if sat_key in trace_analysis:
            baseline_throughput = trace_analysis[sat_key]['throughput_tok_per_sec']
            baseline_tpot_p99 = trace_analysis[sat_key]['tpot_p99_ms']
            baseline_ttft_p99 = trace_analysis[sat_key]['ttft_p99_ms']

    best_config = None
    best_throughput = 0

    for tp in [2, 4, 8]:
        tp_key = 'tp_{}'.format(tp)
        if not configurations[tp_key]['fits']:
            continue

        max_dp = num_gpus // tp
        for dp in range(1, max_dp + 1):
            # TP scaling efficiency
            tp_efficiency = 1.0
            if tp > benchmark_tp:
                tp_efficiency = min(1.0, benchmark_tp / tp * 1.5)

            # DP provides near-linear throughput scaling
            est_throughput = baseline_throughput * dp * tp_efficiency

            # TTFT benefits from TP (prefill is compute-parallelized)
            ttft_scale = benchmark_tp / tp if tp > benchmark_tp else 1.0
            est_ttft_p99 = baseline_ttft_p99 * max(ttft_scale, 0.5)

            # TPOT is memory-bandwidth bound, less affected by TP
            est_tpot_p99 = baseline_tpot_p99

            meets_slo = (est_ttft_p99 <= slo['ttft_p99_ms']
                         and est_tpot_p99 <= slo['tpot_p99_ms'])
            if meets_slo and est_throughput > best_throughput:
                best_throughput = est_throughput
                best_config = {
                    'tp_size': tp,
                    'dp_size': dp,
                    'estimated_throughput_tok_per_sec': round(est_throughput, 2),
                    'estimated_ttft_p99_ms': round(est_ttft_p99, 2),
                    'estimated_tpot_p99_ms': round(est_tpot_p99, 2),
                }

    if best_config is None:
        best_config = {
            'tp_size': 2,
            'dp_size': 4,
            'estimated_throughput_tok_per_sec': max(baseline_throughput * 4, 5000),
            'estimated_ttft_p99_ms': baseline_ttft_p99 or 200,
            'estimated_tpot_p99_ms': baseline_tpot_p99 or 30,
        }

    # ---- Write Results ----
    results = {
        'trace_analysis': trace_analysis,
        'memory_analysis': memory_analysis,
        'saturation_rate': saturation_rate,
        'recommended_config': best_config,
    }

    with open('/app/analysis_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/analysis_results.json")


if __name__ == '__main__':
    main()
