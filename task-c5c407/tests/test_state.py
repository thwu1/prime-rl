"""Tests for RNA 3D structure quality assessment pipeline.

Independent oracle computes expected values from the PDB files,
then compares against the pipeline's output in results.json,
pairwise_rmsd.json, and quality_report.json.
"""

import json
import math
import os
import pytest
import numpy as np

# ── Normalization tables ──────────────────────────────────────────────

MODIFIED_RESIDUE_MAP = {
    "1MA": "A", "MIA": "A", "6MA": "A", "A2M": "A", "MA6": "A",
    "PSU": "U", "5MU": "U", "H2U": "U", "4SU": "U", "UR3": "U",
    "OMC": "C", "5MC": "C", "CBR": "C",
    "OMG": "G", "2MG": "G", "7MG": "G", "M2G": "G", "1MG": "G", "YG": "G",
}

ATOM_NAME_NORM = {
    "O2*": "O2'", "O3*": "O3'", "O4*": "O4'", "O5*": "O5'",
    "C1*": "C1'", "C2*": "C2'", "C3*": "C3'", "C4*": "C4'", "C5*": "C5'",
}

STANDARD_BASES = {"A", "G", "C", "U"}


# ── Oracle implementation ─────────────────────────────────────────────

def parse_pdb(filepath):
    """Parse PDB file -> coords dict and sequence dict."""
    coords = {}
    sequence = {}
    with open(filepath) as f:
        for line in f:
            if not line.startswith("ATOM"):
                continue
            if len(line) < 54:
                continue
            atom_name = line[12:16].strip()
            resname = line[17:20].strip()
            resnum = int(line[22:26])
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])

            norm_atom = ATOM_NAME_NORM.get(atom_name, atom_name)
            norm_res = MODIFIED_RESIDUE_MAP.get(resname, resname)
            if norm_res not in STANDARD_BASES:
                continue

            sequence[resnum] = norm_res
            coords[(resnum, norm_atom)] = np.array([x, y, z])

    return coords, sequence


def kabsch_rmsd(P, Q):
    """Compute RMSD after optimal Kabsch superposition."""
    pc = P.mean(axis=0)
    qc = Q.mean(axis=0)
    Pc = P - pc
    Qc = Q - qc

    H = Pc.T @ Qc
    U, S, Vt = np.linalg.svd(H)

    d = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, 1.0 if d > 0 else -1.0])
    R = Vt.T @ D @ U.T

    Pc_rot = (R @ Pc.T).T
    diff = Qc - Pc_rot
    rmsd = np.sqrt(np.mean(np.sum(diff ** 2, axis=1)))
    return rmsd, R, pc, qc


def compute_p_value(rmsd, L):
    mu = 3.38 * (L ** 0.44)
    beta = 0.49 * (L ** 0.24)
    z = (rmsd - mu) / beta
    try:
        inner = math.exp(-z)
        return math.exp(-inner)
    except OverflowError:
        return 0.0


def compute_per_residue_rmsd(model_coords, ref_coords, matched, R, pc, qc, ref_resnums):
    by_res = {}
    for key in matched:
        by_res.setdefault(key[0], []).append(key)

    result = []
    for rn in ref_resnums:
        if rn not in by_res:
            result.append(0.0)
            continue
        sq = []
        for key in by_res[rn]:
            p_rot = R @ (model_coords[key] - pc)
            q_cen = ref_coords[key] - qc
            d = q_cen - p_rot
            sq.append(float(np.dot(d, d)))
        result.append(math.sqrt(sum(sq) / len(sq)))
    return result


def oracle_assess(model_path, ref_coords, ref_seq, ref_resnums, L):
    model_coords, _ = parse_pdb(model_path)
    matched = sorted(k for k in ref_coords if k in model_coords)
    n = len(matched)
    if n < 3:
        return None

    P = np.array([model_coords[k] for k in matched])
    Q = np.array([ref_coords[k] for k in matched])
    rmsd, R, pc, qc = kabsch_rmsd(P, Q)
    pval = compute_p_value(rmsd, L)
    pr = compute_per_residue_rmsd(model_coords, ref_coords, matched, R, pc, qc, ref_resnums)

    return {"model": os.path.basename(model_path).replace('.pdb', ''),
            "rmsd": rmsd, "p_value": pval,
            "num_matched_atoms": n, "per_residue_rmsd": pr}


def oracle_pairwise(all_structures, all_names):
    """Compute pairwise Kabsch RMSD matrix."""
    n = len(all_names)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            ci = all_structures[all_names[i]]
            cj = all_structures[all_names[j]]
            matched = sorted(k for k in ci if k in cj)
            if len(matched) < 3:
                continue
            P = np.array([ci[k] for k in matched])
            Q = np.array([cj[k] for k in matched])
            rmsd, _, _, _ = kabsch_rmsd(P, Q)
            matrix[i][j] = float(rmsd)
            matrix[j][i] = float(rmsd)
    return matrix


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def results():
    with open('/app/results.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected():
    ref_coords, ref_seq = parse_pdb('/app/data/reference.pdb')
    ref_resnums = sorted(ref_seq.keys())
    L = len(ref_resnums)

    assessments = []
    for i in range(1, 6):
        name = f"model_{i:02d}"
        a = oracle_assess(f'/app/data/{name}.pdb', ref_coords, ref_seq, ref_resnums, L)
        assessments.append(a)

    ranking = [a["model"] for a in sorted(assessments, key=lambda x: x["rmsd"])]
    assessments.sort(key=lambda x: x["model"])
    return {"assessments": assessments, "ranking": ranking}


@pytest.fixture(scope="module")
def pairwise_results():
    with open('/app/pairwise_rmsd.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def pairwise_expected():
    all_names_list = ['model_01', 'model_02', 'model_03', 'model_04', 'model_05', 'reference']
    all_names = sorted(all_names_list)
    all_structures = {}
    for name in all_names:
        coords, _ = parse_pdb(f'/app/data/{name}.pdb')
        all_structures[name] = coords
    matrix = oracle_pairwise(all_structures, all_names)
    return {"structures": all_names, "matrix": matrix}


@pytest.fixture(scope="module")
def quality_report():
    with open('/app/quality_report.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def quality_expected(expected, pairwise_expected):
    ranking = expected['ranking']
    best_model = ranking[0]
    worst_model = ranking[-1]

    max_atoms = max(a['num_matched_atoms'] for a in expected['assessments'])
    full_cov = sorted([a['model'] for a in expected['assessments']
                       if a['num_matched_atoms'] == max_atoms])
    partial_cov = sorted([a['model'] for a in expected['assessments']
                          if a['num_matched_atoms'] < max_atoms])

    all_names = pairwise_expected['structures']
    pw_matrix = pairwise_expected['matrix']
    model_names = sorted([n for n in all_names if n != 'reference'])
    similar_pairs = []
    for ii in range(len(model_names)):
        for jj in range(ii + 1, len(model_names)):
            ni, nj = model_names[ii], model_names[jj]
            idx_i = all_names.index(ni)
            idx_j = all_names.index(nj)
            if pw_matrix[idx_i][idx_j] < 5.0:
                similar_pairs.append([ni, nj])

    return {
        "best_model": best_model,
        "worst_model": worst_model,
        "structurally_similar_pairs": similar_pairs,
        "full_coverage_models": full_cov,
        "partial_coverage_models": partial_cov,
    }


# ── Tests: results.json structure ─────────────────────────────────────

def test_results_file_exists():
    assert os.path.exists('/app/results.json'), "results.json not found at /app/"


def test_results_structure(results):
    assert 'assessments' in results, "Missing 'assessments' key"
    assert 'ranking' in results, "Missing 'ranking' key"
    assert len(results['assessments']) == 5, f"Expected 5 assessments, got {len(results['assessments'])}"
    assert len(results['ranking']) == 5, f"Expected 5 items in ranking"


def test_all_models_present(results):
    names = {a['model'] for a in results['assessments']}
    expected_names = {f"model_{i:02d}" for i in range(1, 6)}
    assert names == expected_names, f"Models mismatch: {names} vs {expected_names}"


def test_assessment_fields(results):
    for a in results['assessments']:
        for field in ('model', 'rmsd', 'p_value', 'num_matched_atoms', 'per_residue_rmsd'):
            assert field in a, f"Missing field '{field}' in assessment for {a.get('model', '?')}"
        assert isinstance(a['rmsd'], (int, float))
        assert isinstance(a['p_value'], (int, float))
        assert isinstance(a['num_matched_atoms'], int)
        assert isinstance(a['per_residue_rmsd'], list)


# ── Tests: metric values ──────────────────────────────────────────────

def test_rmsd_values(results, expected):
    for exp_a in expected['assessments']:
        res_a = next((a for a in results['assessments'] if a['model'] == exp_a['model']), None)
        assert res_a is not None, f"Model {exp_a['model']} not in results"
        assert abs(res_a['rmsd'] - exp_a['rmsd']) < 0.15, (
            f"RMSD mismatch for {exp_a['model']}: "
            f"got {res_a['rmsd']:.4f}, expected {exp_a['rmsd']:.4f}")


def test_p_values(results, expected):
    for exp_a in expected['assessments']:
        res_a = next(a for a in results['assessments'] if a['model'] == exp_a['model'])
        exp_p = exp_a['p_value']
        res_p = res_a['p_value']

        if exp_p < 1e-100:
            assert res_p < 1e-10, (
                f"P-value for {exp_a['model']} should be near zero, got {res_p}")
        else:
            ok = abs(res_p - exp_p) < 0.02 or (exp_p > 0 and abs(res_p - exp_p) / exp_p < 0.15)
            assert ok, (
                f"P-value mismatch for {exp_a['model']}: "
                f"got {res_p:.6e}, expected {exp_p:.6e}")


def test_num_matched_atoms(results, expected):
    for exp_a in expected['assessments']:
        res_a = next(a for a in results['assessments'] if a['model'] == exp_a['model'])
        assert res_a['num_matched_atoms'] == exp_a['num_matched_atoms'], (
            f"Matched atoms mismatch for {exp_a['model']}: "
            f"got {res_a['num_matched_atoms']}, expected {exp_a['num_matched_atoms']}")


def test_ranking(results, expected):
    assert results['ranking'] == expected['ranking'], (
        f"Ranking mismatch:\n  got      {results['ranking']}\n  expected {expected['ranking']}")


def test_ranking_consistency(results):
    rmsds = {a['model']: a['rmsd'] for a in results['assessments']}
    ranking = results['ranking']
    for i in range(len(ranking) - 1):
        assert rmsds[ranking[i]] <= rmsds[ranking[i + 1]] + 0.01, (
            f"Ranking inconsistent: {ranking[i]} ({rmsds[ranking[i]]:.4f}) > "
            f"{ranking[i + 1]} ({rmsds[ranking[i + 1]]:.4f})")


def test_per_residue_rmsd_length(results, expected):
    for exp_a in expected['assessments']:
        res_a = next(a for a in results['assessments'] if a['model'] == exp_a['model'])
        assert len(res_a['per_residue_rmsd']) == len(exp_a['per_residue_rmsd']), (
            f"Per-residue RMSD length mismatch for {exp_a['model']}: "
            f"got {len(res_a['per_residue_rmsd'])}, expected {len(exp_a['per_residue_rmsd'])}")


def test_per_residue_rmsd_values(results, expected):
    for exp_a in expected['assessments']:
        res_a = next(a for a in results['assessments'] if a['model'] == exp_a['model'])
        for j, (got, exp) in enumerate(zip(res_a['per_residue_rmsd'],
                                            exp_a['per_residue_rmsd'])):
            assert abs(got - exp) < 0.3, (
                f"Per-residue RMSD mismatch for {exp_a['model']} residue {j + 1}: "
                f"got {got:.4f}, expected {exp:.4f}")


# ── Tests: structural invariants ──────────────────────────────────────

def test_model04_superposition(results):
    """Model 04 is rotated/translated but same noise level as model 01."""
    rmsds = {a['model']: a['rmsd'] for a in results['assessments']}
    diff = abs(rmsds['model_01'] - rmsds['model_04'])
    assert diff < 2.0, (
        f"Models 01 and 04 should have similar RMSD (same noise level), "
        f"but got {rmsds['model_01']:.4f} vs {rmsds['model_04']:.4f}")


def test_model05_fewer_matched_atoms(results):
    """Model 05 has missing atoms, so fewer matched atoms than models 01-04."""
    counts = {a['model']: a['num_matched_atoms'] for a in results['assessments']}
    assert counts['model_05'] < counts['model_01'], (
        f"model_05 should have fewer matched atoms than model_01: "
        f"{counts['model_05']} vs {counts['model_01']}")


def test_rmsd_positive(results):
    for a in results['assessments']:
        assert a['rmsd'] > 0, f"RMSD should be positive for {a['model']}"


def test_p_value_range(results):
    for a in results['assessments']:
        assert 0.0 <= a['p_value'] <= 1.0, (
            f"P-value out of range for {a['model']}: {a['p_value']}")


# ── Tests: pairwise RMSD matrix ──────────────────────────────────────

def test_pairwise_file_exists():
    assert os.path.exists('/app/pairwise_rmsd.json'), "pairwise_rmsd.json not found at /app/"


def test_pairwise_structure(pairwise_results):
    assert 'structures' in pairwise_results, "Missing 'structures' key"
    assert 'matrix' in pairwise_results, "Missing 'matrix' key"
    assert len(pairwise_results['structures']) == 6, (
        f"Expected 6 structures, got {len(pairwise_results['structures'])}")
    assert len(pairwise_results['matrix']) == 6, (
        f"Expected 6x6 matrix, got {len(pairwise_results['matrix'])} rows")
    for i, row in enumerate(pairwise_results['matrix']):
        assert len(row) == 6, f"Row {i} has {len(row)} elements, expected 6"


def test_pairwise_names(pairwise_results):
    names = pairwise_results['structures']
    expected_names = sorted(['model_01', 'model_02', 'model_03',
                             'model_04', 'model_05', 'reference'])
    assert names == expected_names, (
        f"Structure names mismatch:\n  got      {names}\n  expected {expected_names}")


def test_pairwise_diagonal(pairwise_results):
    for i in range(6):
        assert abs(pairwise_results['matrix'][i][i]) < 0.01, (
            f"Diagonal entry [{i}][{i}] should be 0.0, "
            f"got {pairwise_results['matrix'][i][i]}")


def test_pairwise_symmetric(pairwise_results):
    m = pairwise_results['matrix']
    for i in range(6):
        for j in range(i + 1, 6):
            assert abs(m[i][j] - m[j][i]) < 0.01, (
                f"Matrix not symmetric at [{i}][{j}]: "
                f"{m[i][j]:.4f} vs {m[j][i]:.4f}")


def test_pairwise_values(pairwise_results, pairwise_expected):
    names_got = pairwise_results['structures']
    names_exp = pairwise_expected['structures']
    assert names_got == names_exp, (
        f"Pairwise structure names mismatch: {names_got} vs {names_exp}")

    for i in range(6):
        for j in range(6):
            got = pairwise_results['matrix'][i][j]
            exp = pairwise_expected['matrix'][i][j]
            assert abs(got - exp) < 0.3, (
                f"Pairwise RMSD mismatch [{names_exp[i]}][{names_exp[j]}]: "
                f"got {got:.4f}, expected {exp:.4f}")


def test_pairwise_positive_offdiag(pairwise_results):
    """Off-diagonal entries should be positive (different structures)."""
    m = pairwise_results['matrix']
    for i in range(6):
        for j in range(6):
            if i != j:
                assert m[i][j] > 0, (
                    f"Off-diagonal entry [{i}][{j}] should be positive, got {m[i][j]}")


def test_pairwise_consistent_with_results(results, pairwise_results):
    """Reference-vs-model entries in pairwise matrix should match results.json RMSD."""
    pw_names = pairwise_results['structures']
    ref_idx = pw_names.index('reference')
    pw_matrix = pairwise_results['matrix']

    for a in results['assessments']:
        model_idx = pw_names.index(a['model'])
        pw_rmsd = pw_matrix[ref_idx][model_idx]
        assert abs(pw_rmsd - a['rmsd']) < 0.15, (
            f"Pairwise RMSD for {a['model']} vs reference ({pw_rmsd:.4f}) "
            f"inconsistent with results.json RMSD ({a['rmsd']:.4f})")


# ── Tests: quality_report.json ───────────────────────────────────────

def test_quality_report_file_exists():
    assert os.path.exists('/app/quality_report.json'), "quality_report.json not found at /app/"


def test_quality_report_structure(quality_report):
    assert 'best_model' in quality_report, "Missing 'best_model' key"
    assert 'worst_model' in quality_report, "Missing 'worst_model' key"
    assert 'structurally_similar_pairs' in quality_report, "Missing 'structurally_similar_pairs' key"
    assert 'coverage_analysis' in quality_report, "Missing 'coverage_analysis' key"
    ca = quality_report['coverage_analysis']
    assert 'full_coverage_models' in ca, "Missing 'full_coverage_models' in coverage_analysis"
    assert 'partial_coverage_models' in ca, "Missing 'partial_coverage_models' in coverage_analysis"


def test_best_model(quality_report, quality_expected):
    assert quality_report['best_model'] == quality_expected['best_model'], (
        f"best_model mismatch: got {quality_report['best_model']}, "
        f"expected {quality_expected['best_model']}")


def test_worst_model(quality_report, quality_expected):
    assert quality_report['worst_model'] == quality_expected['worst_model'], (
        f"worst_model mismatch: got {quality_report['worst_model']}, "
        f"expected {quality_expected['worst_model']}")


def test_best_worst_consistent_with_ranking(quality_report, results):
    """best_model should be first in ranking, worst_model should be last."""
    ranking = results['ranking']
    assert quality_report['best_model'] == ranking[0], (
        f"best_model {quality_report['best_model']} != first in ranking {ranking[0]}")
    assert quality_report['worst_model'] == ranking[-1], (
        f"worst_model {quality_report['worst_model']} != last in ranking {ranking[-1]}")


def test_similar_pairs(quality_report, quality_expected):
    got = quality_report['structurally_similar_pairs']
    exp = quality_expected['structurally_similar_pairs']
    # Normalize: sort each pair and then sort list of pairs
    got_norm = sorted([sorted(p) for p in got])
    exp_norm = sorted([sorted(p) for p in exp])
    assert got_norm == exp_norm, (
        f"structurally_similar_pairs mismatch:\n  got      {got_norm}\n  expected {exp_norm}")


def test_similar_pairs_excludes_reference(quality_report):
    """Similar pairs should only contain models, not reference."""
    for pair in quality_report['structurally_similar_pairs']:
        for name in pair:
            assert name != 'reference', (
                f"structurally_similar_pairs should not contain 'reference', found in {pair}")


def test_similar_pairs_threshold(quality_report, pairwise_results):
    """Verify that reported similar pairs actually have pairwise RMSD < 5.0."""
    pw_names = pairwise_results['structures']
    pw_matrix = pairwise_results['matrix']
    for pair in quality_report['structurally_similar_pairs']:
        idx_a = pw_names.index(pair[0])
        idx_b = pw_names.index(pair[1])
        rmsd = pw_matrix[idx_a][idx_b]
        assert rmsd < 5.0, (
            f"Pair {pair} reported as similar but pairwise RMSD is {rmsd:.4f} >= 5.0")


def test_full_coverage_models(quality_report, quality_expected):
    got = sorted(quality_report['coverage_analysis']['full_coverage_models'])
    exp = sorted(quality_expected['full_coverage_models'])
    assert got == exp, (
        f"full_coverage_models mismatch:\n  got      {got}\n  expected {exp}")


def test_partial_coverage_models(quality_report, quality_expected):
    got = sorted(quality_report['coverage_analysis']['partial_coverage_models'])
    exp = sorted(quality_expected['partial_coverage_models'])
    assert got == exp, (
        f"partial_coverage_models mismatch:\n  got      {got}\n  expected {exp}")


def test_coverage_partition(quality_report, results):
    """Full + partial coverage models should equal all models."""
    ca = quality_report['coverage_analysis']
    all_cov = sorted(ca['full_coverage_models'] + ca['partial_coverage_models'])
    all_models = sorted([a['model'] for a in results['assessments']])
    assert all_cov == all_models, (
        f"Coverage partition does not cover all models:\n  coverage: {all_cov}\n  models: {all_models}")


def test_partial_has_fewer_atoms(quality_report, results):
    """Partial coverage models should have strictly fewer matched atoms than full coverage."""
    ca = quality_report['coverage_analysis']
    atom_counts = {a['model']: a['num_matched_atoms'] for a in results['assessments']}
    if ca['full_coverage_models'] and ca['partial_coverage_models']:
        max_full = max(atom_counts[m] for m in ca['full_coverage_models'])
        for m in ca['partial_coverage_models']:
            assert atom_counts[m] < max_full, (
                f"Partial coverage model {m} has {atom_counts[m]} atoms, "
                f"not less than max full coverage {max_full}")
