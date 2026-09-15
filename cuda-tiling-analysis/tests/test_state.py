"""
Tests for CUDA warptiling configuration audit task.

"""

import json
import math
import csv
import sqlite3
import itertools
import os
import pytest


WARPSIZE = 32


# ──────────────────────────────────────────────────────────
# Ground-truth constraint checker and resource calculators
# ──────────────────────────────────────────────────────────

def _is_valid(p):
    """Return (True, None) or (False, reason_string)."""
    BM, BN, BK = p["BM"], p["BN"], p["BK"]
    WM, WN, WNITER = p["WM"], p["WN"], p["WNITER"]
    TM, TN, NT = p["TM"], p["TN"], p["NUM_THREADS"]
    NW = NT // WARPSIZE

    if BN % WN != 0:
        return False, "BN%WN"
    if BM % WM != 0:
        return False, "BM%WM"
    if (BN // WN) * (BM // WM) != NW:
        return False, "warp_count"
    if (WM * WN) % (WARPSIZE * TM * TN * WNITER) != 0:
        return False, "wm_wn_divisibility"
    WMI = (WM * WN) // (WARPSIZE * TM * TN * WNITER)
    if WMI < 1:
        return False, "wmiter<1"
    if WM % WMI != 0:
        return False, "WM%WMITER"
    if WN % WNITER != 0:
        return False, "WN%WNITER"
    if (NT * 4) % BK != 0:
        return False, "NT4%BK"
    if (NT * 4) % BN != 0:
        return False, "NT4%BN"
    if BN % (16 * TN) != 0:
        return False, "BN%16TN"
    if BM % (16 * TM) != 0:
        return False, "BM%16TM"
    if (BM * BK) % (4 * NT) != 0:
        return False, "BMBK%4NT"
    if (BN * BK) % (4 * NT) != 0:
        return False, "BNBK%4NT"

    # Implicit constraints from kernel code patterns
    if TN % 4 != 0:
        return False, "TN%4_float4"
    WSUBN = WN // WNITER
    if WSUBN % TN != 0:
        return False, "WSUBN%TN"
    WSUBM = WM // WMI
    if WSUBM % TM != 0:
        return False, "WSUBM%TM"
    smem = (BM + BN) * BK * 4
    if smem > 49152:
        return False, "smem_limit"
    if NT > 1024:
        return False, "thread_limit"

    return True, None


def _smem(p):
    return (p["BM"] + p["BN"]) * p["BK"] * 4


def _regs(p):
    WMI = (p["WM"] * p["WN"]) // (WARPSIZE * p["TM"] * p["TN"] * p["WNITER"])
    r = WMI * p["TM"] * p["WNITER"] * p["TN"] + WMI * p["TM"] + p["WNITER"] * p["TN"] + 20
    return min(r, 255)


def _occupancy_and_bottleneck(nt, smem, regs, gpu):
    """Compute theoretical occupancy and identify the limiting resource."""
    ws = gpu["warp_size"]
    wpb = nt // ws
    sa = gpu["smem_alloc_granularity_bytes"]
    es = math.ceil(smem / sa) * sa if smem > 0 else 0
    if es > gpu["max_smem_per_block_bytes"]:
        return 0.0, "smem"
    bs = gpu["smem_per_sm_bytes"] // es if es > 0 else gpu["max_blocks_per_sm"]
    ra = gpu["reg_alloc_granularity"]
    rpw = math.ceil(regs * ws / ra) * ra
    rpb = rpw * wpb
    br = gpu["max_regs_per_sm"] // rpb if rpb > 0 else gpu["max_blocks_per_sm"]
    bw = gpu["max_warps_per_sm"] // wpb
    bl = gpu["max_blocks_per_sm"]

    resource_blocks = {"blocks": bl, "regs": br, "smem": bs, "warps": bw}
    min_val = min(resource_blocks.values())
    bottleneck = sorted(k for k, v in resource_blocks.items() if v == min_val)[0]

    ab = max(min(bs, br, bw, bl), 0)
    occ = (ab * wpb) / gpu["max_warps_per_sm"]
    return round(occ, 6), bottleneck


def _load_gpu_specs(db_path="/app/gpu_specs.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT gpu_name FROM gpu_specs ORDER BY gpu_name")
    gpu_names = [row[0] for row in cursor.fetchall()]
    gpus = {}
    for name in gpu_names:
        cursor.execute(
            "SELECT spec_key, spec_value FROM gpu_specs WHERE gpu_name = ?",
            (name,),
        )
        specs = {}
        for key, value in cursor.fetchall():
            try:
                specs[key] = int(value)
            except ValueError:
                specs[key] = value
        gpus[name] = specs
    conn.close()
    return gpus


def _load_param_ranges(csv_path="/app/param_ranges.csv"):
    ranges = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            param = row["parameter"]
            values = [int(v) for v in row["values"].split("|")]
            ranges[param] = values
    return ranges


# ──────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def gpu_specs():
    return _load_gpu_specs()


@pytest.fixture(scope="module")
def param_ranges():
    return _load_param_ranges()


@pytest.fixture(scope="module")
def team_analysis():
    with open("/app/team_analysis.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def results():
    assert os.path.exists("/app/audit_results.json"), "audit_results.json not found"
    with open("/app/audit_results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def all_valid_configs(param_ranges, gpu_specs):
    """Enumerate all valid configs with occupancy and bottleneck per GPU."""
    names = ["BM", "BN", "BK", "WM", "WN", "WNITER", "TM", "TN", "NUM_THREADS"]
    vals = [param_ranges[n] for n in names]
    valid = []
    for combo in itertools.product(*vals):
        p = dict(zip(names, combo))
        ok, _ = _is_valid(p)
        if ok:
            s = _smem(p)
            r = _regs(p)
            occ = {}
            bneck = {}
            for gn, gs in gpu_specs.items():
                o, b = _occupancy_and_bottleneck(p["NUM_THREADS"], s, r, gs)
                occ[gn] = o
                bneck[gn] = b
            valid.append({"params": p, "smem": s, "regs": r, "occ": occ, "bottleneck": bneck})
    return valid


@pytest.fixture(scope="module")
def expected_best(all_valid_configs, gpu_specs):
    """Find the true best config per GPU with tiebreaking."""
    gpu_names = list(gpu_specs.keys())
    best = {}
    for gn in gpu_names:
        sorted_cfgs = sorted(
            all_valid_configs,
            key=lambda c: (-c["occ"][gn], c["smem"], c["params"]["NUM_THREADS"],
                           c["params"]["BM"], c["params"]["BN"])
        )
        best[gn] = sorted_cfgs[0]
    return best


@pytest.fixture(scope="module")
def expected_pareto_count(all_valid_configs, gpu_specs):
    """Compute the Pareto-optimal count independently."""
    gpu_names = list(gpu_specs.keys())
    count = 0
    for i, v in enumerate(all_valid_configs):
        dominated = False
        for j, u in enumerate(all_valid_configs):
            if i == j:
                continue
            if (all(u["occ"][g] >= v["occ"][g] for g in gpu_names) and
                    any(u["occ"][g] > v["occ"][g] for g in gpu_names)):
                dominated = True
                break
        if not dominated:
            count += 1
    return count


@pytest.fixture(scope="module")
def expected_audits(team_analysis, gpu_specs):
    """Compute expected audit results for each team config."""
    gpu_names = sorted(gpu_specs.keys())
    audits = {}
    for name, cfg in team_analysis["configs"].items():
        p = cfg["params"]
        actually_valid, _ = _is_valid(p)
        validity_error = cfg["claimed_valid"] != actually_valid

        if actually_valid:
            s = _smem(p)
            r = _regs(p)
            correct_occ = {}
            correct_bneck = {}
            for gn, gs in gpu_specs.items():
                o, b = _occupancy_and_bottleneck(p["NUM_THREADS"], s, r, gs)
                correct_occ[gn] = o
                correct_bneck[gn] = b

            occ_errors = sorted([
                gn for gn in gpu_names
                if abs(cfg["claimed_occupancy"][gn] - correct_occ[gn]) > 1e-4
            ])
            bneck_errors = sorted([
                gn for gn in gpu_names
                if cfg["claimed_bottleneck"][gn] != correct_bneck[gn]
            ])
        else:
            correct_occ = None
            correct_bneck = None
            occ_errors = []
            bneck_errors = []

        error_count = (1 if validity_error else 0) + len(occ_errors) + len(bneck_errors)

        audits[name] = {
            "actually_valid": actually_valid,
            "validity_error": validity_error,
            "correct_occupancy": correct_occ,
            "correct_bottleneck": correct_bneck,
            "occupancy_errors": occ_errors,
            "bottleneck_errors": bneck_errors,
            "error_count": error_count
        }
    return audits


# ──────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────

class TestResultsSchema:
    def test_file_is_valid_json(self, results):
        assert isinstance(results, dict)

    def test_has_config_audits(self, results):
        assert "config_audits" in results
        assert isinstance(results["config_audits"], dict)

    def test_has_best_pick_audit(self, results):
        assert "best_pick_audit" in results
        for gpu in ["A6000", "A100", "H100"]:
            assert gpu in results["best_pick_audit"]

    def test_has_total_valid_configs(self, results):
        assert "total_valid_configs" in results
        assert isinstance(results["total_valid_configs"], int)

    def test_has_pareto_optimal_count(self, results):
        assert "pareto_optimal_count" in results
        assert isinstance(results["pareto_optimal_count"], int)

    def test_has_portability_scores(self, results):
        assert "portability_scores" in results
        assert isinstance(results["portability_scores"], dict)

    def test_has_total_errors_found(self, results):
        assert "total_errors_found" in results
        assert isinstance(results["total_errors_found"], int)

    def test_all_configs_audited(self, results, team_analysis):
        for name in team_analysis["configs"]:
            assert name in results["config_audits"], f"Missing audit for {name}"


class TestConfigAuditValidity:
    """Verify each config's validity assessment."""

    def test_config_alpha_valid(self, results, expected_audits):
        assert results["config_audits"]["config_alpha"]["actually_valid"] == \
               expected_audits["config_alpha"]["actually_valid"]

    def test_config_beta_invalid(self, results, expected_audits):
        """Config beta uses TN=2 which violates the implicit float4 vectorized
        writeback constraint (TN must be divisible by 4)."""
        assert results["config_audits"]["config_beta"]["actually_valid"] == \
               expected_audits["config_beta"]["actually_valid"]

    def test_config_gamma_valid(self, results, expected_audits):
        assert results["config_audits"]["config_gamma"]["actually_valid"] == \
               expected_audits["config_gamma"]["actually_valid"]

    def test_config_delta_valid(self, results, expected_audits):
        assert results["config_audits"]["config_delta"]["actually_valid"] == \
               expected_audits["config_delta"]["actually_valid"]

    def test_config_epsilon_valid(self, results, expected_audits):
        assert results["config_audits"]["config_epsilon"]["actually_valid"] == \
               expected_audits["config_epsilon"]["actually_valid"]

    def test_config_zeta_invalid(self, results, expected_audits):
        """Config zeta requires 65536 bytes SMEM per block, exceeding the
        49152-byte hardware limit."""
        assert results["config_audits"]["config_zeta"]["actually_valid"] == \
               expected_audits["config_zeta"]["actually_valid"]


class TestConfigAuditValidityErrors:
    """Verify validity error detection."""

    def test_alpha_no_validity_error(self, results):
        assert results["config_audits"]["config_alpha"]["validity_error"] is False

    def test_beta_validity_error_detected(self, results):
        assert results["config_audits"]["config_beta"]["validity_error"] is True

    def test_gamma_no_validity_error(self, results):
        assert results["config_audits"]["config_gamma"]["validity_error"] is False

    def test_delta_no_validity_error(self, results):
        assert results["config_audits"]["config_delta"]["validity_error"] is False

    def test_epsilon_no_validity_error(self, results):
        assert results["config_audits"]["config_epsilon"]["validity_error"] is False

    def test_zeta_validity_error_detected(self, results):
        assert results["config_audits"]["config_zeta"]["validity_error"] is True


class TestConfigAuditOccupancy:
    """Verify correct occupancy values for valid configs."""

    def test_alpha_occupancy_a6000(self, results, expected_audits):
        actual = results["config_audits"]["config_alpha"]["correct_occupancy"]["A6000"]
        expected = expected_audits["config_alpha"]["correct_occupancy"]["A6000"]
        assert abs(actual - expected) < 1e-4, (
            f"config_alpha A6000 occupancy: got {actual}, expected {expected}"
        )

    def test_alpha_occupancy_a100(self, results, expected_audits):
        actual = results["config_audits"]["config_alpha"]["correct_occupancy"]["A100"]
        expected = expected_audits["config_alpha"]["correct_occupancy"]["A100"]
        assert abs(actual - expected) < 1e-4

    def test_alpha_occupancy_h100(self, results, expected_audits):
        actual = results["config_audits"]["config_alpha"]["correct_occupancy"]["H100"]
        expected = expected_audits["config_alpha"]["correct_occupancy"]["H100"]
        assert abs(actual - expected) < 1e-4

    def test_gamma_occupancy_all(self, results, expected_audits):
        for gpu in ["A6000", "A100", "H100"]:
            actual = results["config_audits"]["config_gamma"]["correct_occupancy"][gpu]
            expected = expected_audits["config_gamma"]["correct_occupancy"][gpu]
            assert abs(actual - expected) < 1e-4, (
                f"config_gamma {gpu} occupancy: got {actual}, expected {expected}"
            )

    def test_delta_occupancy_all(self, results, expected_audits):
        for gpu in ["A6000", "A100", "H100"]:
            actual = results["config_audits"]["config_delta"]["correct_occupancy"][gpu]
            expected = expected_audits["config_delta"]["correct_occupancy"][gpu]
            assert abs(actual - expected) < 1e-4

    def test_epsilon_occupancy_all(self, results, expected_audits):
        for gpu in ["A6000", "A100", "H100"]:
            actual = results["config_audits"]["config_epsilon"]["correct_occupancy"][gpu]
            expected = expected_audits["config_epsilon"]["correct_occupancy"][gpu]
            assert abs(actual - expected) < 1e-4

    def test_invalid_configs_null_occupancy(self, results):
        for name in ["config_beta", "config_zeta"]:
            audit = results["config_audits"][name]
            assert audit["correct_occupancy"] is None, (
                f"{name} should have null correct_occupancy since it is invalid"
            )


class TestConfigAuditBottleneck:
    """Verify correct bottleneck classification for valid configs."""

    def test_alpha_bottleneck_a6000(self, results, expected_audits):
        actual = results["config_audits"]["config_alpha"]["correct_bottleneck"]["A6000"]
        expected = expected_audits["config_alpha"]["correct_bottleneck"]["A6000"]
        assert actual == expected, (
            f"config_alpha A6000 bottleneck: got '{actual}', expected '{expected}'"
        )

    def test_alpha_bottleneck_a100(self, results, expected_audits):
        actual = results["config_audits"]["config_alpha"]["correct_bottleneck"]["A100"]
        expected = expected_audits["config_alpha"]["correct_bottleneck"]["A100"]
        assert actual == expected

    def test_alpha_bottleneck_h100(self, results, expected_audits):
        actual = results["config_audits"]["config_alpha"]["correct_bottleneck"]["H100"]
        expected = expected_audits["config_alpha"]["correct_bottleneck"]["H100"]
        assert actual == expected

    def test_gamma_bottleneck_a6000(self, results, expected_audits):
        """Gamma on A6000 is smem-limited, not register-limited as team claimed."""
        actual = results["config_audits"]["config_gamma"]["correct_bottleneck"]["A6000"]
        expected = expected_audits["config_gamma"]["correct_bottleneck"]["A6000"]
        assert actual == expected

    def test_gamma_bottleneck_a100(self, results, expected_audits):
        actual = results["config_audits"]["config_gamma"]["correct_bottleneck"]["A100"]
        expected = expected_audits["config_gamma"]["correct_bottleneck"]["A100"]
        assert actual == expected

    def test_delta_bottleneck_all(self, results, expected_audits):
        for gpu in ["A6000", "A100", "H100"]:
            actual = results["config_audits"]["config_delta"]["correct_bottleneck"][gpu]
            expected = expected_audits["config_delta"]["correct_bottleneck"][gpu]
            assert actual == expected

    def test_epsilon_bottleneck_all(self, results, expected_audits):
        for gpu in ["A6000", "A100", "H100"]:
            actual = results["config_audits"]["config_epsilon"]["correct_bottleneck"][gpu]
            expected = expected_audits["config_epsilon"]["correct_bottleneck"][gpu]
            assert actual == expected

    def test_invalid_configs_null_bottleneck(self, results):
        for name in ["config_beta", "config_zeta"]:
            audit = results["config_audits"][name]
            assert audit["correct_bottleneck"] is None, (
                f"{name} should have null correct_bottleneck since it is invalid"
            )


class TestErrorDetection:
    """Verify that specific team errors are correctly flagged."""

    def test_alpha_occupancy_errors(self, results, expected_audits):
        """Team claimed A6000 occupancy 0.667, actual is 0.5."""
        actual = sorted(results["config_audits"]["config_alpha"]["occupancy_errors"])
        expected = expected_audits["config_alpha"]["occupancy_errors"]
        assert actual == expected, (
            f"config_alpha occupancy_errors: got {actual}, expected {expected}"
        )

    def test_alpha_bottleneck_errors(self, results, expected_audits):
        """Team claimed A6000 bottleneck 'regs', actual is 'smem'."""
        actual = sorted(results["config_audits"]["config_alpha"]["bottleneck_errors"])
        expected = expected_audits["config_alpha"]["bottleneck_errors"]
        assert actual == expected

    def test_gamma_no_occupancy_errors(self, results):
        assert results["config_audits"]["config_gamma"]["occupancy_errors"] == []

    def test_gamma_bottleneck_errors(self, results, expected_audits):
        """Team claimed A6000 bottleneck 'regs', actual is 'smem'."""
        actual = sorted(results["config_audits"]["config_gamma"]["bottleneck_errors"])
        expected = expected_audits["config_gamma"]["bottleneck_errors"]
        assert actual == expected

    def test_delta_no_errors(self, results):
        audit = results["config_audits"]["config_delta"]
        assert audit["validity_error"] is False
        assert audit["occupancy_errors"] == []
        assert audit["bottleneck_errors"] == []

    def test_epsilon_no_errors(self, results):
        audit = results["config_audits"]["config_epsilon"]
        assert audit["validity_error"] is False
        assert audit["occupancy_errors"] == []
        assert audit["bottleneck_errors"] == []

    def test_invalid_configs_empty_error_lists(self, results):
        for name in ["config_beta", "config_zeta"]:
            audit = results["config_audits"][name]
            assert audit["occupancy_errors"] == [], (
                f"{name} is invalid; occupancy_errors should be empty"
            )
            assert audit["bottleneck_errors"] == [], (
                f"{name} is invalid; bottleneck_errors should be empty"
            )

    def test_total_errors_found(self, results, expected_audits):
        expected_total = sum(ea["error_count"] for ea in expected_audits.values())
        assert results["total_errors_found"] == expected_total, (
            f"total_errors_found: got {results['total_errors_found']}, "
            f"expected {expected_total}"
        )


class TestBestPickAudit:
    """Verify best pick audit results for each GPU."""

    def test_a6000_pick_valid(self, results):
        assert results["best_pick_audit"]["A6000"]["team_pick_valid"] is True

    def test_a6000_pick_not_optimal(self, results, expected_best):
        """Team's A6000 pick (config_alpha, occ=0.5) is not the global max."""
        assert results["best_pick_audit"]["A6000"]["team_pick_optimal"] is False

    def test_a6000_actual_best_occupancy(self, results, expected_best):
        actual = results["best_pick_audit"]["A6000"]["actual_best_occupancy"]
        expected = expected_best["A6000"]["occ"]["A6000"]
        assert abs(actual - expected) < 1e-4, (
            f"A6000 actual best occupancy: got {actual}, expected {expected}"
        )

    def test_a6000_actual_best_exceeds_team_pick(self, results):
        """The true best occupancy for A6000 must be strictly higher than 0.5."""
        assert results["best_pick_audit"]["A6000"]["actual_best_occupancy"] > 0.5 + 1e-4

    def test_a6000_actual_best_config_valid(self, results):
        cfg = results["best_pick_audit"]["A6000"]["actual_best_config"]
        ok, reason = _is_valid(cfg)
        assert ok, f"A6000 actual best config is invalid: {reason}"

    def test_a6000_actual_best_config_occupancy_matches(self, results, gpu_specs):
        cfg = results["best_pick_audit"]["A6000"]["actual_best_config"]
        s = _smem(cfg)
        r = _regs(cfg)
        occ, _ = _occupancy_and_bottleneck(cfg["NUM_THREADS"], s, r, gpu_specs["A6000"])
        expected = results["best_pick_audit"]["A6000"]["actual_best_occupancy"]
        assert abs(occ - expected) < 1e-4

    def test_a100_pick_valid(self, results):
        assert results["best_pick_audit"]["A100"]["team_pick_valid"] is True

    def test_a100_pick_not_optimal(self, results, expected_best):
        assert results["best_pick_audit"]["A100"]["team_pick_optimal"] is False

    def test_a100_actual_best_occupancy(self, results, expected_best):
        actual = results["best_pick_audit"]["A100"]["actual_best_occupancy"]
        expected = expected_best["A100"]["occ"]["A100"]
        assert abs(actual - expected) < 1e-4

    def test_a100_actual_best_config_valid(self, results):
        cfg = results["best_pick_audit"]["A100"]["actual_best_config"]
        ok, reason = _is_valid(cfg)
        assert ok, f"A100 actual best config is invalid: {reason}"

    def test_h100_pick_invalid(self, results):
        """Team's H100 pick (config_zeta) is actually invalid due to SMEM overflow."""
        assert results["best_pick_audit"]["H100"]["team_pick_valid"] is False

    def test_h100_pick_not_optimal(self, results):
        assert results["best_pick_audit"]["H100"]["team_pick_optimal"] is False

    def test_h100_actual_best_occupancy(self, results, expected_best):
        actual = results["best_pick_audit"]["H100"]["actual_best_occupancy"]
        expected = expected_best["H100"]["occ"]["H100"]
        assert abs(actual - expected) < 1e-4

    def test_h100_actual_best_config_valid(self, results):
        cfg = results["best_pick_audit"]["H100"]["actual_best_config"]
        ok, reason = _is_valid(cfg)
        assert ok, f"H100 actual best config is invalid: {reason}"

    def test_best_occupancy_in_valid_range(self, results):
        for gpu in ["A6000", "A100", "H100"]:
            occ = results["best_pick_audit"][gpu]["actual_best_occupancy"]
            assert 0.0 < occ <= 1.0, f"{gpu} best occupancy {occ} out of range (0,1]"


class TestTotalCount:
    def test_total_valid_configs(self, results, all_valid_configs):
        expected = len(all_valid_configs)
        actual = results["total_valid_configs"]
        assert actual == expected, (
            f"total_valid_configs: got {actual}, expected {expected}"
        )

    def test_total_count_positive(self, results):
        assert results["total_valid_configs"] > 0


class TestParetoOptimal:
    def test_pareto_count(self, results, expected_pareto_count):
        actual = results["pareto_optimal_count"]
        assert actual == expected_pareto_count, (
            f"pareto_optimal_count: got {actual}, expected {expected_pareto_count}"
        )

    def test_pareto_count_positive(self, results):
        assert results["pareto_optimal_count"] > 0

    def test_pareto_count_le_total(self, results):
        assert results["pareto_optimal_count"] <= results["total_valid_configs"]


class TestPortabilityScores:
    """Verify portability scores for each team config."""

    def test_invalid_configs_null(self, results, expected_audits):
        for name, ea in expected_audits.items():
            if not ea["actually_valid"]:
                assert results["portability_scores"][name] is None, (
                    f"{name} portability should be null (config is invalid)"
                )

    def test_valid_configs_portability(self, results, expected_audits):
        for name, ea in expected_audits.items():
            if not ea["actually_valid"]:
                continue
            occ_values = list(ea["correct_occupancy"].values())
            expected_port = round(min(occ_values) / max(occ_values), 6)
            actual = results["portability_scores"][name]
            assert abs(actual - expected_port) < 1e-4, (
                f"{name} portability: got {actual}, expected {expected_port}"
            )

    def test_all_configs_have_portability(self, results, team_analysis):
        for name in team_analysis["configs"]:
            assert name in results["portability_scores"], (
                f"Missing portability score for {name}"
            )


class TestConsistency:
    """Cross-check consistency between different output sections."""

    def test_best_occupancy_gte_team_valid_picks(self, results, expected_audits):
        """Best actual occupancy should be >= any valid team config's occupancy."""
        for gpu in ["A6000", "A100", "H100"]:
            best_occ = results["best_pick_audit"][gpu]["actual_best_occupancy"]
            for name, ea in expected_audits.items():
                if ea["actually_valid"]:
                    team_occ = ea["correct_occupancy"][gpu]
                    assert best_occ >= team_occ - 1e-4, (
                        f"{gpu}: best_occ {best_occ} < {name} occ {team_occ}"
                    )

    def test_errors_breakdown_matches_total(self, results, expected_audits):
        """Sum of individual error counts matches total_errors_found."""
        total = 0
        for name in expected_audits:
            audit = results["config_audits"][name]
            count = (1 if audit["validity_error"] else 0) + \
                    len(audit["occupancy_errors"]) + \
                    len(audit["bottleneck_errors"])
            total += count
        assert results["total_errors_found"] == total

    def test_cross_architecture_bottleneck_variation(self, results, expected_audits):
        """At least one valid team config should show different bottlenecks
        across GPU architectures, confirming architecture-aware analysis."""
        found = False
        for name, ea in expected_audits.items():
            if not ea["actually_valid"]:
                continue
            bneck_vals = set(results["config_audits"][name]["correct_bottleneck"].values())
            if len(bneck_vals) > 1:
                found = True
                break
        assert found, (
            "Expected at least one valid config with different bottlenecks across GPUs"
        )

    def test_portability_range(self, results, expected_audits):
        """All portability scores should be in (0, 1]."""
        for name, ea in expected_audits.items():
            if not ea["actually_valid"]:
                continue
            score = results["portability_scores"][name]
            assert 0.0 < score <= 1.0, (
                f"{name} portability {score} out of range (0,1]"
            )
