"""Verification tests for branch predictor design-space analysis.


Tests independently compute correct values from raw simulation data and verify
the agent's outputs: results.json, analysis.db, and designspace.png.
"""

import json
import math
import os
import sqlite3
import pytest


# ============================================================
# Reference VFS implementation
# ============================================================
IPCBP0 = 8
CPICBP0 = 0.0315
EPICBP0 = 1000

ALPHA = 1.625
BETA = 4 * ALPHA / (ALPHA - 1) ** 2
GAMMA = 2 / (ALPHA - 1)

CBP_ENERGY_RATIO = 0.05
WPI0 = IPCBP0 * CPICBP0

P2_TO_EXEC_STAGES = 9

DATA_DIR = '/app/data'
TRACES_JSON = '/app/traces.json'


def load_trace_categories():
    """Load trace-to-category mapping and category weights."""
    with open(TRACES_JSON) as f:
        meta = json.load(f)
    trace_to_cat = {}
    cat_weights = {}
    for cat_name, cat_info in meta['categories'].items():
        cat_weights[cat_name] = cat_info['weight']
        for trace in cat_info['traces']:
            trace_to_cat[trace] = cat_name
    return trace_to_cat, cat_weights


def read_trace_data(pred_dir):
    """Read all .out files and return list of field arrays."""
    data = []
    for filename in sorted(os.listdir(pred_dir)):
        if not filename.endswith('.out'):
            continue
        with open(os.path.join(pred_dir, filename)) as f:
            line = f.readline().strip()
            if line:
                data.append(line.split(','))
    return data


def compute_latencies(trace_data):
    """Compute max ceil(P1), max ceil(P2) across all traces."""
    p1 = 0
    p2 = 0
    for fields in trace_data:
        p1 = max(p1, math.ceil(float(fields[9])))
        p2 = max(p2, math.ceil(float(fields[10])))
    return p1, p2


def per_trace_metrics(fields, p1_latency, p2_latency):
    """Compute IPC, CPI, EPI for a single trace."""
    instructions = float(fields[1])
    npred = float(fields[4])
    extra_cycles = float(fields[5])
    divergences = float(fields[6])
    div_at_end = float(fields[7])
    mispredictions = float(fields[8])
    epi = float(fields[11])

    if p2_latency <= p1_latency:
        cycles = npred * max(1, p2_latency)
    else:
        cycles = (npred * max(1, p1_latency)
                  + divergences * p2_latency
                  - div_at_end * max(1, p1_latency))
    cycles += extra_cycles

    ipc = instructions / cycles
    mpi = mispredictions / instructions
    cpi = mpi * (P2_TO_EXEC_STAGES + p2_latency
                 - max(1, min(p1_latency, p2_latency)))

    return ipc, cpi, epi


def aggregate_metrics(metric_tuples):
    """Aggregate (ipc, cpi, epi) tuples: harmonic IPC, arithmetic CPI/EPI."""
    n = len(metric_tuples)
    sum_inv_ipc = sum(1.0 / m[0] for m in metric_tuples)
    avg_ipc = n / sum_inv_ipc
    avg_cpi = sum(m[1] for m in metric_tuples) / n
    avg_epi = sum(m[2] for m in metric_tuples) / n
    return avg_ipc, avg_cpi, avg_epi


def aggregate_predictor(pred_dir):
    """Compute standard aggregate metrics for a predictor."""
    data = read_trace_data(pred_dir)
    p1, p2 = compute_latencies(data)
    metrics = [per_trace_metrics(f, p1, p2) for f in data]
    ipc, cpi, epi = aggregate_metrics(metrics)
    return {'ipc_cbp': ipc, 'cpi_cbp': cpi, 'epi_cbp': epi}


def compute_weighted_metrics(pred_dir):
    """Compute workload-weighted aggregate metrics."""
    trace_to_cat, cat_weights = load_trace_categories()
    data = read_trace_data(pred_dir)
    p1, p2 = compute_latencies(data)

    # Group per-trace metrics by category
    cat_metrics = {}
    for fields in data:
        trace_name = fields[0]
        cat = trace_to_cat.get(trace_name)
        if cat is None:
            continue
        ipc, cpi, epi = per_trace_metrics(fields, p1, p2)
        if cat not in cat_metrics:
            cat_metrics[cat] = []
        cat_metrics[cat].append((ipc, cpi, epi))

    # Per-category aggregation
    cat_agg = {}
    for cat, metrics in cat_metrics.items():
        cat_agg[cat] = aggregate_metrics(metrics)

    # Weighted harmonic mean for IPC, weighted arithmetic for CPI, EPI
    sum_w_over_ipc = 0.0
    sum_w_cpi = 0.0
    sum_w_epi = 0.0
    for cat, (ipc, cpi, epi) in cat_agg.items():
        w = cat_weights[cat]
        sum_w_over_ipc += w / ipc
        sum_w_cpi += w * cpi
        sum_w_epi += w * epi

    return {
        'ipc_cbp': 1.0 / sum_w_over_ipc,
        'cpi_cbp': sum_w_cpi,
        'epi_cbp': sum_w_epi,
    }


def compute_per_category_vfs_for_predictor(pred_dir):
    """Compute VFS score per workload category for a predictor."""
    trace_to_cat, cat_weights = load_trace_categories()
    data = read_trace_data(pred_dir)
    p1, p2 = compute_latencies(data)

    cat_metrics = {}
    for fields in data:
        trace_name = fields[0]
        cat = trace_to_cat.get(trace_name)
        if cat is None:
            continue
        ipc, cpi, epi = per_trace_metrics(fields, p1, p2)
        cat_metrics.setdefault(cat, []).append((ipc, cpi, epi))

    cat_vfs = {}
    for cat, metrics in cat_metrics.items():
        c_ipc, c_cpi, c_epi = aggregate_metrics(metrics)
        cat_vfs[cat] = compute_vfs(c_ipc, c_cpi, c_epi)

    return cat_vfs


def compute_vfs(ipc, cpi, epi):
    """Compute VFS score."""
    wpi = ipc * cpi
    speedup = (ipc / IPCBP0) * (1 + WPI0) / (1 + wpi)

    lam = 1 / (1 + WPI0 / 2) - CBP_ENERGY_RATIO

    normalized_epi = ((epi / EPICBP0) * CBP_ENERGY_RATIO
                      + lam * speedup ** GAMMA) * (1 + wpi / 2)

    vfs = speedup * ALPHA * (
        1 - 2 / (1 + math.sqrt(1 + BETA / (speedup * normalized_epi)))
    )
    return vfs


def find_pareto_optimal(metrics):
    """Find Pareto-optimal predictors in (IPC up, CPI down, EPI down) space."""
    names = list(metrics.keys())
    pareto = []
    dominated = []

    for name_i in names:
        is_dominated = False
        pi = metrics[name_i]
        for name_j in names:
            if name_i == name_j:
                continue
            pj = metrics[name_j]
            if (pj['ipc_cbp'] >= pi['ipc_cbp']
                    and pj['cpi_cbp'] <= pi['cpi_cbp']
                    and pj['epi_cbp'] <= pi['epi_cbp']
                    and (pj['ipc_cbp'] > pi['ipc_cbp']
                         or pj['cpi_cbp'] < pi['cpi_cbp']
                         or pj['epi_cbp'] < pi['epi_cbp'])):
                is_dominated = True
                break
        if is_dominated:
            dominated.append(name_i)
        else:
            pareto.append(name_i)

    return sorted(pareto), sorted(dominated)


def compute_elasticity(ipc, cpi, epi, delta=0.001):
    """Compute VFS elasticity numerically via central differences."""
    vfs_base = compute_vfs(ipc, cpi, epi)

    vfs_up = compute_vfs(ipc * (1 + delta), cpi, epi)
    vfs_dn = compute_vfs(ipc * (1 - delta), cpi, epi)
    e_ipc = (vfs_up - vfs_dn) / (2 * delta * ipc) * ipc / vfs_base

    vfs_up = compute_vfs(ipc, cpi * (1 + delta), epi)
    vfs_dn = compute_vfs(ipc, cpi * (1 - delta), epi)
    e_cpi = (vfs_up - vfs_dn) / (2 * delta * cpi) * cpi / vfs_base

    vfs_up = compute_vfs(ipc, cpi, epi * (1 + delta))
    vfs_dn = compute_vfs(ipc, cpi, epi * (1 - delta))
    e_epi = (vfs_up - vfs_dn) / (2 * delta * epi) * epi / vfs_base

    return {'ipc': e_ipc, 'cpi': e_cpi, 'epi': e_epi}


# ============================================================
# Compute all reference answers from raw data
# ============================================================
@pytest.fixture(scope='module')
def reference():
    """Compute all reference answers from raw simulation data."""
    trace_to_cat, cat_weights = load_trace_categories()

    # Standard metrics
    all_metrics = {}
    for pred in sorted(os.listdir(DATA_DIR)):
        pred_path = os.path.join(DATA_DIR, pred)
        if not os.path.isdir(pred_path):
            continue
        all_metrics[pred] = aggregate_predictor(pred_path)

    vfs_scores = {n: compute_vfs(m['ipc_cbp'], m['cpi_cbp'], m['epi_cbp'])
                  for n, m in all_metrics.items()}

    ranking = sorted(vfs_scores, key=vfs_scores.get, reverse=True)
    best = ranking[0]

    pareto, dominated = find_pareto_optimal(all_metrics)

    bp = all_metrics[best]
    elasticity = compute_elasticity(bp['ipc_cbp'], bp['cpi_cbp'], bp['epi_cbp'])
    abs_e = {k: abs(v) for k, v in elasticity.items()}
    optimal = max(abs_e, key=abs_e.get)

    # Workload-weighted metrics
    weighted_metrics = {}
    for pred in sorted(os.listdir(DATA_DIR)):
        pred_path = os.path.join(DATA_DIR, pred)
        if not os.path.isdir(pred_path):
            continue
        weighted_metrics[pred] = compute_weighted_metrics(pred_path)

    weighted_vfs = {n: compute_vfs(m['ipc_cbp'], m['cpi_cbp'], m['epi_cbp'])
                    for n, m in weighted_metrics.items()}

    weighted_ranking = sorted(weighted_vfs, key=weighted_vfs.get, reverse=True)

    # Per-category VFS
    per_category_vfs = {}
    for pred in sorted(os.listdir(DATA_DIR)):
        pred_path = os.path.join(DATA_DIR, pred)
        if not os.path.isdir(pred_path):
            continue
        per_category_vfs[pred] = compute_per_category_vfs_for_predictor(pred_path)

    # Category specialists
    category_specialists = {}
    for cat in cat_weights:
        best_pred = max(
            (p for p in per_category_vfs if cat in per_category_vfs[p]),
            key=lambda p: per_category_vfs[p][cat]
        )
        category_specialists[cat] = best_pred

    # Rank stability
    rank_stability = {}
    for i, pred in enumerate(ranking):
        std_rank = i + 1
        w_rank = weighted_ranking.index(pred) + 1
        shift = abs(std_rank - w_rank)
        if shift <= 1:
            cls = "stable"
        elif shift <= 3:
            cls = "workload-sensitive"
        else:
            cls = "highly-sensitive"
        rank_stability[pred] = {
            "standard_rank": std_rank,
            "weighted_rank": w_rank,
            "shift": shift,
            "classification": cls
        }

    # Most efficient (highest VFS / EPI ratio)
    most_efficient = max(vfs_scores,
                         key=lambda n: vfs_scores[n] / all_metrics[n]['epi_cbp'])

    return {
        'vfs_scores': vfs_scores,
        'ranking': ranking,
        'best_predictor': best,
        'best_vfs': vfs_scores[best],
        'pareto_optimal': pareto,
        'dominated': dominated,
        'elasticity': elasticity,
        'optimal_improvement': optimal,
        'all_metrics': all_metrics,
        'weighted_vfs_scores': weighted_vfs,
        'weighted_ranking': weighted_ranking,
        'per_category_vfs': per_category_vfs,
        'category_specialists': category_specialists,
        'rank_stability': rank_stability,
        'most_efficient': most_efficient,
    }


@pytest.fixture(scope='module')
def results():
    """Load the agent's results.json."""
    path = '/app/results.json'
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        return json.load(f)


# ============================================================
# Tests: Results structure
# ============================================================
class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), \
            "results.json must exist at /app/results.json"

    def test_results_is_valid_json(self, results):
        assert isinstance(results, dict)

    def test_has_required_keys(self, results):
        required = ['vfs_scores', 'ranking', 'best_predictor', 'best_vfs',
                     'pareto_optimal', 'dominated', 'elasticity_at_best',
                     'optimal_improvement', 'weighted_vfs_scores',
                     'weighted_ranking', 'per_category_vfs',
                     'category_specialists', 'rank_stability',
                     'most_efficient']
        for key in required:
            assert key in results, f"Missing key: {key}"


# ============================================================
# Tests: SQLite database
# ============================================================
class TestSQLiteDatabase:
    def test_database_exists(self):
        assert os.path.exists('/app/analysis.db'), \
            "SQLite database not found at /app/analysis.db"

    def test_database_is_valid_sqlite(self):
        with open('/app/analysis.db', 'rb') as f:
            header = f.read(16)
        assert header[:6] == b'SQLite', \
            "analysis.db is not a valid SQLite database"

    def test_database_has_tables(self):
        conn = sqlite3.connect('/app/analysis.db')
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            assert len(tables) >= 2, \
                f"Expected at least 2 tables, found {len(tables)}: {tables}"
        finally:
            conn.close()

    def test_database_has_raw_data(self):
        conn = sqlite3.connect('/app/analysis.db')
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            total_rows = 0
            for table in tables:
                cursor = conn.execute(f'SELECT COUNT(*) FROM "{table}"')
                total_rows += cursor.fetchone()[0]
            assert total_rows >= 150, \
                f"Expected >= 150 total rows (10 predictors x 15 traces), " \
                f"found {total_rows}"
        finally:
            conn.close()

    def test_database_has_metrics_table(self):
        conn = sqlite3.connect('/app/analysis.db')
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            has_metrics = False
            for table in tables:
                cursor = conn.execute(f'SELECT COUNT(*) FROM "{table}"')
                count = cursor.fetchone()[0]
                if 10 <= count <= 40:
                    has_metrics = True
                    break
            assert has_metrics, \
                "No table found with 10-40 rows (expected per-predictor metrics)"
        finally:
            conn.close()


# ============================================================
# Tests: gnuplot visualization
# ============================================================
class TestGnuplotVisualization:
    def test_designspace_png_exists(self):
        assert os.path.exists('/app/designspace.png'), \
            "Design space visualization not found at /app/designspace.png"

    def test_designspace_png_is_valid(self):
        with open('/app/designspace.png', 'rb') as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', \
            "designspace.png is not a valid PNG file"

    def test_designspace_png_not_empty(self):
        size = os.path.getsize('/app/designspace.png')
        assert size > 1024, \
            f"designspace.png too small ({size} bytes), likely corrupt or empty"


# ============================================================
# Tests: Standard VFS scores
# ============================================================
class TestVFSScores:
    def test_all_predictors_scored(self, results, reference):
        for name in reference['vfs_scores']:
            assert name in results['vfs_scores'], \
                f"Missing VFS score for {name}"

    def test_vfs_values_correct(self, results, reference):
        for name, expected in reference['vfs_scores'].items():
            actual = results['vfs_scores'][name]
            assert abs(actual - expected) < 0.001, (
                f"VFS for {name}: expected {expected:.6f}, got {actual:.6f}"
            )

    def test_no_extra_predictors(self, results, reference):
        for name in results['vfs_scores']:
            assert name in reference['vfs_scores'], \
                f"Unexpected predictor: {name}"


# ============================================================
# Tests: Ranking
# ============================================================
class TestRanking:
    def test_ranking_correct(self, results, reference):
        assert results['ranking'] == reference['ranking'], (
            f"Expected ranking: {reference['ranking']}, "
            f"got: {results['ranking']}"
        )

    def test_best_predictor(self, results, reference):
        assert results['best_predictor'] == reference['best_predictor'], (
            f"Expected best: {reference['best_predictor']}, "
            f"got: {results['best_predictor']}"
        )

    def test_best_vfs_value(self, results, reference):
        assert abs(results['best_vfs'] - reference['best_vfs']) < 0.001, (
            f"Expected best VFS: {reference['best_vfs']:.6f}, "
            f"got: {results['best_vfs']}"
        )


# ============================================================
# Tests: Pareto analysis
# ============================================================
class TestParetoAnalysis:
    def test_pareto_optimal_set(self, results, reference):
        expected = set(reference['pareto_optimal'])
        actual = set(results['pareto_optimal'])
        assert actual == expected, (
            f"Expected Pareto: {expected}, got: {actual}"
        )

    def test_dominated_set(self, results, reference):
        expected = set(reference['dominated'])
        actual = set(results['dominated'])
        assert actual == expected, (
            f"Expected dominated: {expected}, got: {actual}"
        )

    def test_partition_covers_all(self, results, reference):
        all_preds = set(reference['vfs_scores'].keys())
        actual_all = set(results['pareto_optimal']) | set(results['dominated'])
        assert actual_all == all_preds


# ============================================================
# Tests: Elasticity
# ============================================================
class TestElasticity:
    def test_ipc_elasticity_sign(self, results, reference):
        ref = reference['elasticity']['ipc']
        actual = results['elasticity_at_best']['ipc']
        if abs(ref) > 0.01:
            assert (actual > 0) == (ref > 0), (
                f"IPC elasticity sign mismatch: expected ~{ref:.6f}, "
                f"got {actual:.6f}"
            )

    def test_cpi_elasticity_negative(self, results, reference):
        actual = results['elasticity_at_best']['cpi']
        assert actual < 0, (
            f"CPI elasticity should be negative, got {actual:.6f}"
        )

    def test_epi_elasticity_negative(self, results, reference):
        actual = results['elasticity_at_best']['epi']
        assert actual < 0, (
            f"EPI elasticity should be negative, got {actual:.6f}"
        )

    def test_elasticity_values_close(self, results, reference):
        for key in ['ipc', 'cpi', 'epi']:
            expected = reference['elasticity'][key]
            actual = results['elasticity_at_best'][key]
            assert abs(actual - expected) < 0.05, (
                f"Elasticity {key}: expected {expected:.6f}, got {actual:.6f}"
            )

    def test_optimal_improvement(self, results, reference):
        assert results['optimal_improvement'] == reference['optimal_improvement'], (
            f"Expected optimal: {reference['optimal_improvement']}, "
            f"got: {results['optimal_improvement']}"
        )


# ============================================================
# Tests: Workload-weighted VFS
# ============================================================
class TestWeightedVFS:
    def test_weighted_scores_present(self, results, reference):
        for name in reference['weighted_vfs_scores']:
            assert name in results['weighted_vfs_scores'], \
                f"Missing weighted VFS score for {name}"

    def test_weighted_scores_correct(self, results, reference):
        for name, expected in reference['weighted_vfs_scores'].items():
            actual = results['weighted_vfs_scores'][name]
            assert abs(actual - expected) < 0.001, (
                f"Weighted VFS for {name}: expected {expected:.6f}, "
                f"got {actual:.6f}"
            )

    def test_weighted_ranking_correct(self, results, reference):
        assert results['weighted_ranking'] == reference['weighted_ranking'], (
            f"Expected weighted ranking: {reference['weighted_ranking']}, "
            f"got: {results['weighted_ranking']}"
        )

    def test_no_extra_weighted_predictors(self, results, reference):
        for name in results['weighted_vfs_scores']:
            assert name in reference['weighted_vfs_scores'], \
                f"Unexpected predictor in weighted scores: {name}"


# ============================================================
# Tests: Per-category VFS
# ============================================================
class TestPerCategoryVFS:
    def test_per_category_vfs_present(self, results, reference):
        for pred in reference['per_category_vfs']:
            assert pred in results['per_category_vfs'], \
                f"Missing per-category VFS for {pred}"

    def test_per_category_vfs_all_categories(self, results, reference):
        for pred, cats in reference['per_category_vfs'].items():
            for cat in cats:
                assert cat in results['per_category_vfs'][pred], (
                    f"Missing category {cat} for predictor {pred}"
                )

    def test_per_category_vfs_values(self, results, reference):
        for pred, cats in reference['per_category_vfs'].items():
            for cat, expected in cats.items():
                actual = results['per_category_vfs'][pred][cat]
                assert abs(actual - expected) < 0.001, (
                    f"Per-category VFS for {pred}/{cat}: "
                    f"expected {expected:.6f}, got {actual:.6f}"
                )

    def test_no_extra_predictors_in_per_category(self, results, reference):
        for pred in results['per_category_vfs']:
            assert pred in reference['per_category_vfs'], \
                f"Unexpected predictor in per_category_vfs: {pred}"


# ============================================================
# Tests: Category specialists
# ============================================================
class TestCategorySpecialists:
    def test_category_specialists_present(self, results):
        assert 'category_specialists' in results

    def test_category_specialists_correct(self, results, reference):
        for cat, expected in reference['category_specialists'].items():
            assert cat in results['category_specialists'], \
                f"Missing category specialist for {cat}"
            actual = results['category_specialists'][cat]
            assert actual == expected, (
                f"Category {cat} specialist: expected {expected}, got {actual}"
            )

    def test_category_specialists_all_categories(self, results, reference):
        expected_cats = set(reference['category_specialists'].keys())
        actual_cats = set(results['category_specialists'].keys())
        assert actual_cats == expected_cats, (
            f"Expected categories: {expected_cats}, got: {actual_cats}"
        )


# ============================================================
# Tests: Rank stability
# ============================================================
class TestRankStability:
    def test_rank_stability_present(self, results, reference):
        for pred in reference['rank_stability']:
            assert pred in results['rank_stability'], \
                f"Missing rank stability for {pred}"

    def test_rank_stability_positions(self, results, reference):
        for pred, expected in reference['rank_stability'].items():
            actual = results['rank_stability'][pred]
            assert actual['standard_rank'] == expected['standard_rank'], (
                f"{pred} standard_rank: expected {expected['standard_rank']}, "
                f"got {actual['standard_rank']}"
            )
            assert actual['weighted_rank'] == expected['weighted_rank'], (
                f"{pred} weighted_rank: expected {expected['weighted_rank']}, "
                f"got {actual['weighted_rank']}"
            )

    def test_rank_stability_shift(self, results, reference):
        for pred, expected in reference['rank_stability'].items():
            actual = results['rank_stability'][pred]
            assert actual['shift'] == expected['shift'], (
                f"{pred} shift: expected {expected['shift']}, "
                f"got {actual['shift']}"
            )

    def test_rank_stability_classification(self, results, reference):
        for pred, expected in reference['rank_stability'].items():
            actual = results['rank_stability'][pred]
            assert actual['classification'] == expected['classification'], (
                f"{pred} classification: expected {expected['classification']}, "
                f"got {actual['classification']}"
            )


# ============================================================
# Tests: Most efficient
# ============================================================
class TestMostEfficient:
    def test_most_efficient_present(self, results):
        assert 'most_efficient' in results

    def test_most_efficient_correct(self, results, reference):
        assert results['most_efficient'] == reference['most_efficient'], (
            f"Expected most efficient: {reference['most_efficient']}, "
            f"got: {results['most_efficient']}"
        )

    def test_most_efficient_is_valid_predictor(self, results, reference):
        assert results['most_efficient'] in reference['vfs_scores'], \
            f"most_efficient '{results['most_efficient']}' is not a known predictor"


# ============================================================
# Tests: VFS formula sanity checks
# ============================================================
class TestVFSFormulaSanity:
    def test_reference_predictor_vfs_near_one(self):
        """A predictor matching reference values should have VFS near 1.0."""
        vfs_ref = compute_vfs(8, 0.0315, 1000)
        assert abs(vfs_ref - 1.0) < 0.01, (
            f"Reference VFS should be ~1.0, got {vfs_ref:.6f}"
        )

    def test_scores_in_reasonable_range(self, results):
        """All VFS scores should be between 0.3 and 1.5."""
        for name, score in results['vfs_scores'].items():
            assert 0.3 < score < 1.5, (
                f"VFS for {name} = {score} is out of reasonable range"
            )

    def test_always_taken_ranks_last(self, results):
        """always_taken should have the lowest VFS score."""
        assert results['ranking'][-1] == 'always_taken', (
            "always_taken should rank last"
        )

    def test_weighted_scores_in_range(self, results):
        """All weighted VFS scores should also be in reasonable range."""
        for name, score in results['weighted_vfs_scores'].items():
            assert 0.3 < score < 1.5, (
                f"Weighted VFS for {name} = {score} out of range"
            )

    def test_per_category_scores_in_range(self, results):
        """All per-category VFS scores should be in reasonable range."""
        for pred, cats in results['per_category_vfs'].items():
            for cat, score in cats.items():
                assert 0.3 < score < 1.5, (
                    f"Per-category VFS for {pred}/{cat} = {score} out of range"
                )
