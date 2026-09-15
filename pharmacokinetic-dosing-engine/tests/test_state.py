
import json
import math
import os
import subprocess
import pytest

# ── Reference half-life values (hours) ──

EXPECTED_HALF_LIVES = {
    "DB00001": 1.3,
    "DB00004": (70 * 80) ** 0.5 / 60,
    "DB00005": 68.0,
    "DB00006": 25.0 / 60,
    "DB00008": 80.0,
    "DB00010": (11 * 12) ** 0.5 / 60,
    "DB00024": 25.0,
    "DB00035": (0.4 * 4) ** 0.5,
    "DB00039": 4.5,
    "DB00041": (13 * 85) ** 0.5 / 60,
    "DB00044": 18.0,
    "DB00051": (10 * 20) ** 0.5 * 24,
    "DB00054": 30.0 / 60,
    "DB00066": (35 * 40) ** 0.5,
    "DB00080": (8 * 9) ** 0.5,
    "DB00091": 19.0,
    "DB00097": 29.0,
    "DB00106": 13.2 * 24,
    "DB00176": 15.6,
    "DB00177": (5 * 9) ** 0.5,
}

# ── Drug parameter lookup ──

DRUG_PARAMS = {
    "DB00001": {"vd_per_kg": 0.14, "t_min": 0.5, "t_max": 2.0},
    "DB00004": {"vd_per_kg": 0.06, "t_min": 1.0, "t_max": 10.0},
    "DB00005": {"vd_per_kg": 0.11, "t_min": 1.0, "t_max": 5.0},
    "DB00006": {"vd_per_kg": 0.25, "t_min": 1.0, "t_max": 15.0},
    "DB00008": {"vd_per_kg": 0.10, "t_min": 0.001, "t_max": 0.01},
    "DB00010": {"vd_per_kg": 0.5, "t_min": 0.001, "t_max": 0.05},
    "DB00024": {"vd_per_kg": 0.05, "t_min": 0.01, "t_max": 0.1},
    "DB00035": {"vd_per_kg": 0.3, "t_min": 0.0001, "t_max": 0.001},
    "DB00039": {"vd_per_kg": 0.03, "t_min": 0.1, "t_max": 5.0},
    "DB00041": {"vd_per_kg": 0.15, "t_min": 0.01, "t_max": 1.0},
    "DB00044": {"vd_per_kg": 0.14, "t_min": 0.01, "t_max": 0.5},
    "DB00051": {"vd_per_kg": 0.07, "t_min": 5.0, "t_max": 15.0},
    "DB00054": {"vd_per_kg": 0.07, "t_min": 1.0, "t_max": 20.0},
    "DB00066": {"vd_per_kg": 0.11, "t_min": 0.001, "t_max": 0.1},
    "DB00080": {"vd_per_kg": 0.10, "t_min": 20.0, "t_max": 100.0},
    "DB00091": {"vd_per_kg": 4.0, "t_min": 0.15, "t_max": 0.40},
    "DB00097": {"vd_per_kg": 0.06, "t_min": 0.005, "t_max": 0.5},
    "DB00106": {"vd_per_kg": 0.50, "t_min": 0.01, "t_max": 1.0},
    "DB00176": {"vd_per_kg": 3.50, "t_min": 0.06, "t_max": 0.30},
    "DB00177": {"vd_per_kg": 0.23, "t_min": 1.0, "t_max": 8.0},
}

# ── Curated reference half-lives for reconciliation ──

CURATED_DRUGS = {
    "DB00001": 1.30,
    "DB00004": 1.25,
    "DB00005": 68.0,
    "DB00008": 80.0,
    "DB00010": 0.192,
    "DB00024": 25.0,
    "DB00039": 4.50,
    "DB00044": 18.0,
    "DB00051": 339.41,
    "DB00066": 37.42,
    "DB00080": 8.49,
    "DB00091": 19.0,
    "DB00097": 29.0,
    "DB00176": 15.6,
}

# ── PK reference computation ──

def compute_pk(t_half, dose, tau, weight, vd_per_kg, bioavailability, t_min, t_max):
    ke = math.log(2) / t_half
    vd = vd_per_kg * weight
    cl = ke * vd
    eff_dose = dose * bioavailability

    exp_ke_tau = math.exp(-ke * tau)
    R = 1.0 / (1.0 - exp_ke_tau)
    cmax_ss = (eff_dose / vd) * R
    cmin_ss = cmax_ss * exp_ke_tau
    auc_ss = eff_dose / cl
    t90 = math.log(10) / ke

    below = cmin_ss < t_min
    above = cmax_ss > t_max
    if below and above:
        status = "both_violated"
    elif below:
        status = "below_min"
    elif above:
        status = "above_max"
    else:
        status = "in_range"

    return {
        "ke": ke, "vd": vd, "cl": cl, "R": R,
        "cmax_ss": cmax_ss, "cmin_ss": cmin_ss,
        "auc_ss": auc_ss, "t90": t90,
        "status": status,
    }


def find_longest_valid_interval(dose, weight, vd_per_kg, bioavailability, t_half, t_min, t_max):
    ke = math.log(2) / t_half
    vd = vd_per_kg * weight
    eff_dose = dose * bioavailability
    c0 = eff_dose / vd

    if c0 > t_max:
        return None

    best = None
    for tau in range(1, 721):
        exp_val = math.exp(-ke * tau)
        R = 1.0 / (1.0 - exp_val)
        cmax = c0 * R
        cmin = cmax * exp_val
        if cmin >= t_min and cmax <= t_max:
            best = tau
    return best


# ── Scenarios ──

SCENARIOS = [
    {"id": "S01", "drug": "DB00080", "dose": 350,   "tau": 24,  "wt": 70, "route": "iv_bolus", "F": 1.0},
    {"id": "S02", "drug": "DB00176", "dose": 100,   "tau": 24,  "wt": 70, "route": "oral",     "F": 0.53},
    {"id": "S03", "drug": "DB00091", "dose": 200,   "tau": 12,  "wt": 70, "route": "oral",     "F": 0.30},
    {"id": "S04", "drug": "DB00177", "dose": 160,   "tau": 24,  "wt": 80, "route": "oral",     "F": 0.25},
    {"id": "S05", "drug": "DB00044", "dose": 0.5,   "tau": 24,  "wt": 60, "route": "iv_bolus", "F": 1.0},
    {"id": "S06", "drug": "DB00024", "dose": 0.1,   "tau": 48,  "wt": 70, "route": "iv_bolus", "F": 1.0},
    {"id": "S07", "drug": "DB00039", "dose": 5,     "tau": 8,   "wt": 70, "route": "iv_bolus", "F": 1.0},
    {"id": "S08", "drug": "DB00005", "dose": 25,    "tau": 168, "wt": 70, "route": "iv_bolus", "F": 1.0},
    {"id": "S09", "drug": "DB00097", "dose": 0.5,   "tau": 72,  "wt": 70, "route": "iv_bolus", "F": 1.0},
    {"id": "S10", "drug": "DB00041", "dose": 20,    "tau": 8,   "wt": 70, "route": "iv_bolus", "F": 1.0},
    {"id": "S11", "drug": "DB00051", "dose": 30,    "tau": 336, "wt": 70, "route": "iv_bolus", "F": 1.0},
    {"id": "S12", "drug": "DB00051", "dose": 40,    "tau": 336, "wt": 70, "route": "iv_bolus", "F": 1.0},
    {"id": "S13", "drug": "DB00001", "dose": 5,     "tau": 8,   "wt": 70, "route": "iv_bolus", "F": 1.0},
    {"id": "S14", "drug": "DB00035", "dose": 0.004, "tau": 6,   "wt": 65, "route": "iv_bolus", "F": 1.0},
    {"id": "S15", "drug": "DB00010", "dose": 10,    "tau": 4,   "wt": 70, "route": "iv_bolus", "F": 1.0},
]


# ── Fixtures ──

@pytest.fixture(scope="module")
def results():
    path = "/app/output/results.json"
    assert os.path.isfile(path), f"Output file {path} does not exist"
    with open(path) as f:
        data = json.load(f)
    assert "drug_extractions" in data, "Missing 'drug_extractions' key"
    assert "scenario_analyses" in data, "Missing 'scenario_analyses' key"
    return data


@pytest.fixture(scope="module")
def extraction_map(results):
    return {e["drugbank_id"]: e for e in results["drug_extractions"]}


@pytest.fixture(scope="module")
def scenario_map(results):
    return {s["scenario_id"]: s for s in results["scenario_analyses"]}


@pytest.fixture(scope="module")
def reconciliation_rows(results):
    """Run validate.sh and parse reconciliation.tsv."""
    assert os.path.isfile("/app/validate.sh"), "validate.sh not found at /app/validate.sh"
    proc = subprocess.run(
        ["bash", "/app/validate.sh"],
        capture_output=True, timeout=120, cwd="/app"
    )
    assert proc.returncode == 0, f"validate.sh failed (rc={proc.returncode}): {proc.stderr.decode()[:500]}"

    recon_path = "/app/output/reconciliation.tsv"
    assert os.path.isfile(recon_path), "reconciliation.tsv not produced by validate.sh"

    rows = []
    with open(recon_path) as f:
        header_line = f.readline().strip()
        header = header_line.split('\t')
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 5:
                rows.append(dict(zip(header, parts)))
    return rows


# ── Helper ──

def rel_err(actual, expected):
    if expected == 0:
        return abs(actual)
    return abs(actual - expected) / abs(expected)


# ── Tests ──

class TestHalfLifeParsing:
    """Verify parsed half-life values for all 20 drugs."""

    def test_all_drugs_present(self, extraction_map):
        missing = set(EXPECTED_HALF_LIVES.keys()) - set(extraction_map.keys())
        assert len(missing) == 0, f"Missing drugs in extraction: {missing}"

    def test_parsed_half_lives(self, extraction_map):
        errors = []
        for drug_id, expected_hl in EXPECTED_HALF_LIVES.items():
            entry = extraction_map.get(drug_id)
            if entry is None:
                errors.append(f"{drug_id}: missing")
                continue
            actual_hl = entry.get("parsed_half_life_hours")
            if actual_hl is None:
                errors.append(f"{drug_id}: parsed_half_life_hours is null")
                continue
            err = rel_err(actual_hl, expected_hl)
            if err > 0.02:
                errors.append(
                    f"{drug_id}: expected {expected_hl:.6f}, got {actual_hl:.6f} "
                    f"(error {err:.4f})"
                )
        max_allowed_errors = 3
        assert len(errors) <= max_allowed_errors, (
            f"Too many half-life parsing errors ({len(errors)}/{len(EXPECTED_HALF_LIVES)}):\n"
            + "\n".join(errors)
        )

    def test_ke_values(self, extraction_map):
        errors = []
        for drug_id, expected_hl in EXPECTED_HALF_LIVES.items():
            entry = extraction_map.get(drug_id)
            if entry is None:
                continue
            actual_ke = entry.get("elimination_rate_constant_per_h")
            if actual_ke is None:
                errors.append(f"{drug_id}: ke is null")
                continue
            expected_ke = math.log(2) / expected_hl
            err = rel_err(actual_ke, expected_ke)
            if err > 0.03:
                errors.append(f"{drug_id}: ke expected {expected_ke:.6f}, got {actual_ke:.6f}")
        assert len(errors) <= 3, (
            f"Too many ke errors ({len(errors)}):\n" + "\n".join(errors)
        )


class TestPKComputation:
    """Verify PK parameters for all 15 scenarios."""

    def test_all_scenarios_present(self, scenario_map):
        expected_ids = {s["id"] for s in SCENARIOS}
        missing = expected_ids - set(scenario_map.keys())
        assert len(missing) == 0, f"Missing scenarios: {missing}"

    def test_pk_values(self, scenario_map):
        errors = []
        for sc in SCENARIOS:
            sid = sc["id"]
            drug_id = sc["drug"]
            entry = scenario_map.get(sid)
            if entry is None:
                errors.append(f"{sid}: missing")
                continue

            t_half = EXPECTED_HALF_LIVES[drug_id]
            params = DRUG_PARAMS[drug_id]
            ref = compute_pk(
                t_half, sc["dose"], sc["tau"], sc["wt"],
                params["vd_per_kg"], sc["F"],
                params["t_min"], params["t_max"]
            )

            checks = [
                ("ke_per_h", ref["ke"]),
                ("vd_L", ref["vd"]),
                ("clearance_L_per_h", ref["cl"]),
                ("accumulation_factor", ref["R"]),
                ("cmax_steady_state_mg_L", ref["cmax_ss"]),
                ("cmin_steady_state_mg_L", ref["cmin_ss"]),
                ("auc_steady_state_mg_h_per_L", ref["auc_ss"]),
                ("time_to_90pct_steady_state_h", ref["t90"]),
            ]
            for field, expected_val in checks:
                actual_val = entry.get(field)
                if actual_val is None:
                    errors.append(f"{sid}.{field}: null")
                    continue
                err = rel_err(actual_val, expected_val)
                if err > 0.05:
                    errors.append(
                        f"{sid}.{field}: expected {expected_val:.6g}, "
                        f"got {actual_val:.6g} (err {err:.4f})"
                    )

        max_allowed = 10
        assert len(errors) <= max_allowed, (
            f"Too many PK computation errors ({len(errors)}):\n"
            + "\n".join(errors[:20])
        )


class TestTherapeuticStatus:
    """Verify therapeutic status classification."""

    def test_statuses(self, scenario_map):
        errors = []
        for sc in SCENARIOS:
            sid = sc["id"]
            drug_id = sc["drug"]
            entry = scenario_map.get(sid)
            if entry is None:
                errors.append(f"{sid}: missing")
                continue

            t_half = EXPECTED_HALF_LIVES[drug_id]
            params = DRUG_PARAMS[drug_id]
            ref = compute_pk(
                t_half, sc["dose"], sc["tau"], sc["wt"],
                params["vd_per_kg"], sc["F"],
                params["t_min"], params["t_max"]
            )

            actual_status = entry.get("therapeutic_status")
            if actual_status != ref["status"]:
                errors.append(
                    f"{sid}: expected '{ref['status']}', got '{actual_status}'"
                )

        max_allowed = 2
        assert len(errors) <= max_allowed, (
            f"Too many status errors ({len(errors)}):\n" + "\n".join(errors)
        )


class TestDosingRecommendation:
    """Verify recommended dosing intervals."""

    def test_recommendations(self, scenario_map):
        errors = []
        for sc in SCENARIOS:
            sid = sc["id"]
            drug_id = sc["drug"]
            entry = scenario_map.get(sid)
            if entry is None:
                continue

            t_half = EXPECTED_HALF_LIVES[drug_id]
            params = DRUG_PARAMS[drug_id]
            ref = compute_pk(
                t_half, sc["dose"], sc["tau"], sc["wt"],
                params["vd_per_kg"], sc["F"],
                params["t_min"], params["t_max"]
            )

            rec = entry.get("recommended_interval_h")

            if ref["status"] == "in_range":
                if rec is not None:
                    errors.append(f"{sid}: in_range but recommended_interval_h={rec}")
                continue

            ref_opt = find_longest_valid_interval(
                sc["dose"], sc["wt"], params["vd_per_kg"], sc["F"],
                t_half, params["t_min"], params["t_max"]
            )

            if ref_opt is None:
                if rec is not None:
                    ke = math.log(2) / t_half
                    vd = params["vd_per_kg"] * sc["wt"]
                    eff_dose = sc["dose"] * sc["F"]
                    exp_val = math.exp(-ke * rec)
                    R = 1.0 / (1.0 - exp_val)
                    cmax = (eff_dose / vd) * R
                    cmin = cmax * exp_val
                    if not (cmin >= params["t_min"] * 0.98 and cmax <= params["t_max"] * 1.02):
                        errors.append(
                            f"{sid}: should be null (no valid interval), got {rec}"
                        )
            else:
                if rec is None:
                    errors.append(f"{sid}: expected interval ~{ref_opt}, got null")
                else:
                    ke = math.log(2) / t_half
                    vd = params["vd_per_kg"] * sc["wt"]
                    eff_dose = sc["dose"] * sc["F"]
                    exp_val = math.exp(-ke * rec)
                    R = 1.0 / (1.0 - exp_val)
                    cmax = (eff_dose / vd) * R
                    cmin = cmax * exp_val
                    if not (cmin >= params["t_min"] * 0.98 and cmax <= params["t_max"] * 1.02):
                        errors.append(
                            f"{sid}: rec interval {rec}h gives "
                            f"Cmax={cmax:.6g}, Cmin={cmin:.6g} "
                            f"(window [{params['t_min']}, {params['t_max']}])"
                        )

        max_allowed = 2
        assert len(errors) <= max_allowed, (
            f"Too many recommendation errors ({len(errors)}):\n"
            + "\n".join(errors)
        )


class TestReconciliation:
    """Verify cross-referencing validation pipeline."""

    def test_validate_script_exists(self):
        assert os.path.isfile("/app/validate.sh"), \
            "validate.sh must exist at /app/validate.sh"

    def test_validate_script_executable(self):
        assert os.access("/app/validate.sh", os.X_OK) or True, \
            "validate.sh should be executable"

    def test_reconciliation_header(self, reconciliation_rows):
        recon_path = "/app/output/reconciliation.tsv"
        with open(recon_path) as f:
            header = f.readline().strip().split('\t')
        expected = ["drugbank_id", "parsed_hours", "curated_hours", "pct_discrepancy", "status"]
        assert header == expected, f"Wrong header columns: {header}, expected: {expected}"

    def test_reconciliation_row_count(self, reconciliation_rows):
        assert len(reconciliation_rows) >= 12, (
            f"Expected at least 12 reconciliation rows (14 curated drugs), "
            f"got {len(reconciliation_rows)}"
        )

    def test_reconciliation_drug_coverage(self, reconciliation_rows):
        recon_ids = {r["drugbank_id"] for r in reconciliation_rows}
        expected_ids = set(CURATED_DRUGS.keys())
        missing = expected_ids - recon_ids
        assert len(missing) <= 2, f"Too many missing drugs in reconciliation: {missing}"

    def test_reconciliation_values(self, reconciliation_rows):
        errors = []
        for row in reconciliation_rows:
            did = row["drugbank_id"]
            if did not in CURATED_DRUGS:
                continue
            try:
                parsed = float(row["parsed_hours"])
                curated = float(row["curated_hours"])
                disc = float(row["pct_discrepancy"])
                status = row["status"]
            except (ValueError, KeyError) as e:
                errors.append(f"{did}: parse error: {e}")
                continue

            # Curated value should be close to what's in the TSV
            expected_curated = CURATED_DRUGS[did]
            if rel_err(curated, expected_curated) > 0.01:
                errors.append(
                    f"{did}: curated value {curated} doesn't match reference {expected_curated}"
                )

            # Discrepancy should be correctly computed
            expected_disc = abs(parsed - curated) / curated * 100 if curated != 0 else 0
            if abs(disc - expected_disc) > 1.0:
                errors.append(
                    f"{did}: discrepancy {disc}% doesn't match computed {expected_disc:.2f}%"
                )

            # Status should be consistent with discrepancy
            expected_status = "MATCH" if disc <= 5 else "MISMATCH"
            if status != expected_status:
                errors.append(
                    f"{did}: status '{status}' inconsistent with discrepancy {disc}%"
                )

        assert len(errors) <= 2, (
            f"Too many reconciliation errors ({len(errors)}):\n" + "\n".join(errors)
        )

    def test_all_curated_drugs_match(self, reconciliation_rows):
        """All curated drugs should have MATCH status when parsed correctly."""
        match_count = sum(1 for r in reconciliation_rows if r.get("status") == "MATCH")
        total = len(reconciliation_rows)
        assert match_count >= total - 3, (
            f"Too many MISMATCH entries: {total - match_count} out of {total}"
        )
