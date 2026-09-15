
import json
import os
import sqlite3
import numpy as np
import pytest


DB_PATH = '/app/data/benchmarks.db'


def load_results():
    with open('/app/analysis_results.json') as f:
        return json.load(f)


def load_benchmark(rate):
    """Load all request traces for a given rate from the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
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
        'request_id': row[0],
        'arrival_time': row[1],
        'prompt_len': row[2],
        'output_len': row[3],
        'ttft': row[4],
        'latency': row[5],
        'success': bool(row[6]),
        'itl': json.loads(row[7])
    } for row in rows]


def get_num_runs():
    """Get the total number of benchmark runs from SQLite."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM runs')
    count = cur.fetchone()[0]
    conn.close()
    return count


def get_successful(data):
    return [r for r in data if r.get('success', True)]


def find_rate_key(trace_analysis, rate):
    """Find the key in trace_analysis matching a given request rate."""
    for fmt in ['rate_{}'.format(rate), 'rate_{:.1f}'.format(rate),
                'rate_{}'.format(int(rate))]:
        if fmt in trace_analysis:
            return fmt
    for k, v in trace_analysis.items():
        if isinstance(v, dict) and abs(v.get('request_rate', -999) - rate) < 0.01:
            return k
    return None


def find_tp_config(configs, tp_size):
    """Find configuration entry for a given TP size."""
    for k, v in configs.items():
        if k in ['tp_{}'.format(tp_size), 'tp{}'.format(tp_size),
                  'TP_{}'.format(tp_size), str(tp_size)]:
            return v
        if isinstance(v, dict) and v.get('tp_size') == tp_size:
            return v
    return None


# --- Model architecture constants for verification ---
HIDDEN = 4096
NUM_HEADS = 32
NUM_KV_HEADS = 8
HEAD_DIM = 128
INTERMEDIATE = 14336
VOCAB = 32000
NUM_LAYERS = 32
NUM_EXPERTS = 8
BPP = 2  # bytes per param (bf16)

# Expected total parameters
_embedding = VOCAB * HIDDEN
_lm_head = VOCAB * HIDDEN
_attn_per_layer = (HIDDEN * NUM_HEADS * HEAD_DIM +
                   HIDDEN * NUM_KV_HEADS * HEAD_DIM * 2 +
                   NUM_HEADS * HEAD_DIM * HIDDEN)
_gate_per_layer = HIDDEN * NUM_EXPERTS
_expert_each = HIDDEN * INTERMEDIATE * 3
_moe_per_layer = _gate_per_layer + NUM_EXPERTS * _expert_each
_norm_per_layer = 2 * HIDDEN
_final_norm = HIDDEN
_per_layer = _attn_per_layer + _moe_per_layer + _norm_per_layer
EXPECTED_TOTAL_PARAMS = _embedding + _lm_head + NUM_LAYERS * _per_layer + _final_norm
EXPECTED_TOTAL_BYTES = EXPECTED_TOTAL_PARAMS * BPP
EXPECTED_TOTAL_GB = EXPECTED_TOTAL_BYTES / (1024 ** 3)

EXPECTED_KV_PER_TOKEN = 2 * NUM_LAYERS * NUM_KV_HEADS * HEAD_DIM * BPP  # 131,072

GPU_MEMORY = 85899345920   # 80 GB
MEM_FRACTION = 0.88
USABLE_MEMORY = GPU_MEMORY * MEM_FRACTION


# ======================= OUTPUT FORMAT =======================

class TestOutputFormat:
    def test_file_exists(self):
        assert os.path.exists('/app/analysis_results.json'), \
            "analysis_results.json not found at /app/"

    def test_valid_json(self):
        results = load_results()
        assert isinstance(results, dict), "Top-level JSON must be an object"

    def test_required_sections(self):
        results = load_results()
        assert 'trace_analysis' in results, "Missing trace_analysis"
        assert 'memory_analysis' in results, "Missing memory_analysis"
        assert any(k in results for k in ['saturation_rate', 'max_sustainable_rate']), \
            "Missing saturation_rate or max_sustainable_rate"
        assert 'recommended_config' in results, "Missing recommended_config"


# ======================= TRACE ANALYSIS =======================

class TestTraceAnalysis:
    def test_all_rates_analyzed(self):
        results = load_results()
        num_runs = get_num_runs()
        assert len(results['trace_analysis']) == num_runs, \
            "Expected analysis for all {} benchmark runs".format(num_runs)

    @pytest.mark.parametrize("rate", [2.0, 6.0, 10.0, 14.0, 18.0])
    def test_ttft_percentiles(self, rate):
        results = load_results()
        key = find_rate_key(results['trace_analysis'], rate)
        assert key is not None, "No trace analysis for rate {}".format(rate)

        data = get_successful(load_benchmark(rate))
        ttfts = np.array([r['ttft'] * 1000.0 for r in data])

        actual = results['trace_analysis'][key]
        for pct, name in [(50, 'ttft_p50_ms'), (95, 'ttft_p95_ms'), (99, 'ttft_p99_ms')]:
            expected = float(np.percentile(ttfts, pct))
            tol = max(expected * 0.05, 0.5)
            assert abs(actual[name] - expected) < tol, \
                "Rate {} {}: expected {:.3f}, got {:.3f}".format(rate, name, expected, actual[name])

    @pytest.mark.parametrize("rate", [2.0, 10.0, 18.0])
    def test_tpot_percentiles(self, rate):
        results = load_results()
        key = find_rate_key(results['trace_analysis'], rate)
        assert key is not None

        data = get_successful(load_benchmark(rate))
        tpots = np.array([(r['latency'] - r['ttft']) / max(r['output_len'] - 1, 1) * 1000.0
                          for r in data])

        actual = results['trace_analysis'][key]
        for pct, name in [(50, 'tpot_p50_ms'), (99, 'tpot_p99_ms')]:
            expected = float(np.percentile(tpots, pct))
            tol = max(expected * 0.05, 0.5)
            assert abs(actual[name] - expected) < tol, \
                "Rate {} {}: expected {:.3f}, got {:.3f}".format(rate, name, expected, actual[name])

    @pytest.mark.parametrize("rate", [2.0, 14.0])
    def test_itl_percentiles(self, rate):
        results = load_results()
        key = find_rate_key(results['trace_analysis'], rate)
        assert key is not None

        data = get_successful(load_benchmark(rate))
        all_itls = []
        for r in data:
            all_itls.extend([t * 1000.0 for t in r.get('itl', [])])
        all_itls = np.array(all_itls)

        actual = results['trace_analysis'][key]
        for pct, name in [(50, 'itl_p50_ms'), (99, 'itl_p99_ms')]:
            expected = float(np.percentile(all_itls, pct))
            tol = max(expected * 0.05, 0.5)
            assert abs(actual[name] - expected) < tol, \
                "Rate {} {}: expected {:.3f}, got {:.3f}".format(rate, name, expected, actual[name])

    @pytest.mark.parametrize("rate", [4.0, 10.0, 16.0])
    def test_throughput(self, rate):
        results = load_results()
        key = find_rate_key(results['trace_analysis'], rate)
        assert key is not None

        data = load_benchmark(rate)
        successful = get_successful(data)
        total_tokens = sum(r['output_len'] for r in successful)
        duration = (max(r['arrival_time'] + r['latency'] for r in data) -
                    min(r['arrival_time'] for r in data))
        expected = total_tokens / duration if duration > 0 else 0

        actual = results['trace_analysis'][key]
        tol = max(expected * 0.15, 10.0)
        assert abs(actual['throughput_tok_per_sec'] - expected) < tol, \
            "Rate {} throughput: expected {:.1f}, got {:.1f}".format(
                rate, expected, actual['throughput_tok_per_sec'])


# ======================= MEMORY ANALYSIS =======================

class TestMemoryAnalysis:
    def test_memory_analysis_present(self):
        results = load_results()
        assert 'memory_analysis' in results

    def test_model_weights_total(self):
        results = load_results()
        mem = results['memory_analysis']
        actual_gb = mem['model_weights_total_gb']
        assert abs(actual_gb - EXPECTED_TOTAL_GB) / EXPECTED_TOTAL_GB < 0.002, \
            "Model weight: expected {:.4f} GB, got {:.4f} GB (tolerance 0.2%)".format(
                EXPECTED_TOTAL_GB, actual_gb)

    def test_kv_cache_per_token(self):
        results = load_results()
        mem = results['memory_analysis']
        assert mem['kv_cache_bytes_per_token'] == EXPECTED_KV_PER_TOKEN, \
            "KV cache per token: expected {}, got {}".format(
                EXPECTED_KV_PER_TOKEN, mem['kv_cache_bytes_per_token'])

    def test_tp1_does_not_fit(self):
        results = load_results()
        configs = results['memory_analysis'].get(
            'configurations', results['memory_analysis'].get('configs', {}))
        tp1 = find_tp_config(configs, 1)
        if tp1 is not None:
            assert tp1.get('fits') == False, \
                "TP=1 should not fit: model {:.1f} GB > usable {:.1f} GB".format(
                    EXPECTED_TOTAL_GB, USABLE_MEMORY / (1024**3))

    def test_tp2_fits_with_correct_capacity(self):
        results = load_results()
        configs = results['memory_analysis'].get(
            'configurations', results['memory_analysis'].get('configs', {}))
        tp2 = find_tp_config(configs, 2)
        assert tp2 is not None, "TP=2 configuration not found"
        assert tp2.get('fits') == True, "TP=2 should fit in GPU memory"

        model_per_gpu = EXPECTED_TOTAL_BYTES / 2
        kv_pool = USABLE_MEMORY - model_per_gpu
        kv_per_tok = EXPECTED_KV_PER_TOKEN / 2
        expected_max = int(kv_pool / kv_per_tok)

        if 'max_kv_tokens' in tp2:
            actual_max = tp2['max_kv_tokens']
            assert abs(actual_max - expected_max) / expected_max < 0.02, \
                "TP=2 max_kv_tokens: expected ~{}, got {}".format(expected_max, actual_max)

    def test_tp4_capacity(self):
        results = load_results()
        configs = results['memory_analysis'].get(
            'configurations', results['memory_analysis'].get('configs', {}))
        tp4 = find_tp_config(configs, 4)
        assert tp4 is not None, "TP=4 configuration not found"
        assert tp4.get('fits') == True, "TP=4 should fit"

        model_per_gpu = EXPECTED_TOTAL_BYTES / 4
        kv_pool = USABLE_MEMORY - model_per_gpu
        kv_per_tok = EXPECTED_KV_PER_TOKEN / 4
        expected_max = int(kv_pool / kv_per_tok)

        if 'max_kv_tokens' in tp4:
            actual_max = tp4['max_kv_tokens']
            assert abs(actual_max - expected_max) / expected_max < 0.02, \
                "TP=4 max_kv_tokens: expected ~{}, got {}".format(expected_max, actual_max)

    def test_tp8_capacity(self):
        results = load_results()
        configs = results['memory_analysis'].get(
            'configurations', results['memory_analysis'].get('configs', {}))
        tp8 = find_tp_config(configs, 8)
        assert tp8 is not None, "TP=8 configuration not found"
        assert tp8.get('fits') == True, "TP=8 should fit"

        model_per_gpu = EXPECTED_TOTAL_BYTES / 8
        kv_pool = USABLE_MEMORY - model_per_gpu
        kv_per_tok = EXPECTED_KV_PER_TOKEN / 8
        expected_max = int(kv_pool / kv_per_tok)

        if 'max_kv_tokens' in tp8:
            actual_max = tp8['max_kv_tokens']
            assert abs(actual_max - expected_max) / expected_max < 0.02, \
                "TP=8 max_kv_tokens: expected ~{}, got {}".format(expected_max, actual_max)


# ======================= CONFIGURATION RECOMMENDATION =======================

class TestRecommendation:
    def test_recommendation_present(self):
        results = load_results()
        assert 'recommended_config' in results
        rec = results['recommended_config']
        assert rec is not None, "recommended_config should not be null"

    def test_valid_tp(self):
        results = load_results()
        rec = results['recommended_config']
        assert rec['tp_size'] in [2, 4, 8], \
            "TP must be 2, 4, or 8 (TP=1 does not fit). Got {}".format(rec['tp_size'])

    def test_valid_gpu_count(self):
        results = load_results()
        rec = results['recommended_config']
        total = rec['tp_size'] * rec['dp_size']
        assert total <= 8, \
            "TP*DP = {} exceeds 8 available GPUs".format(total)

    def test_good_utilization(self):
        """Optimal config should use most available GPUs."""
        results = load_results()
        rec = results['recommended_config']
        total = rec['tp_size'] * rec['dp_size']
        assert total >= 4, \
            "Only using {} of 8 GPUs - suboptimal utilization".format(total)

    def test_positive_throughput(self):
        results = load_results()
        rec = results['recommended_config']
        assert rec['estimated_throughput_tok_per_sec'] > 0, \
            "Estimated throughput must be positive"

    def test_saturation_rate_reasonable(self):
        results = load_results()
        rate = results.get('saturation_rate', results.get('max_sustainable_rate'))
        assert rate is not None, "Saturation rate not found"
        assert 8.0 <= rate <= 22.0, \
            "Saturation rate {} out of expected range [8, 22]".format(rate)

    def test_saturation_rate_consistent(self):
        """TTFT p99 at the saturation rate should be at or below SLO."""
        results = load_results()
        sat_rate = results.get('saturation_rate', results.get('max_sustainable_rate'))
        key = find_rate_key(results['trace_analysis'], sat_rate)
        if key is not None:
            entry = results['trace_analysis'][key]
            with open('/app/data/slo_targets.json') as f:
                slo = json.load(f)
            assert entry['ttft_p99_ms'] <= slo['ttft_p99_ms'] * 1.1, \
                "At saturation rate {}, TTFT p99 = {:.1f} ms exceeds SLO {:.1f} ms".format(
                    sat_rate, entry['ttft_p99_ms'], slo['ttft_p99_ms'])

    def test_throughput_meets_slo(self):
        """Recommended config should approach or meet throughput SLO."""
        results = load_results()
        rec = results['recommended_config']
        with open('/app/data/slo_targets.json') as f:
            slo = json.load(f)
        assert rec['estimated_throughput_tok_per_sec'] >= slo['min_throughput_tokens_per_sec'] * 0.7, \
            "Throughput {:.0f} tok/s too low for SLO {} tok/s".format(
                rec['estimated_throughput_tok_per_sec'], slo['min_throughput_tokens_per_sec'])
