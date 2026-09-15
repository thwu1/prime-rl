
"""Verification tests for the ASR system portfolio optimization task.

Independently runs SCTK tools to verify the agent's analysis.json
contains correct WER, per-speaker WER, NCE values, correct calibration
ranking, and that the claimed optimal ROVER configuration (method +
alpha + system subset) is truly optimal across the full parameter space.
"""

import json
import os
import subprocess
from itertools import combinations

RESULTS_FILE = "/app/results/analysis.json"
REF_FILE = "/app/data/reference.stm"
DATA_DIR = "/app/data"
WORK_DIR = "/tmp/test_work"
SYSTEMS = ["sys1", "sys2", "sys3", "sys4"]
SPEAKERS = ["spk1", "spk2"]
WER_TOLERANCE = 0.6  # percentage points
NCE_TOLERANCE = 0.1
ALPHA_VALUES = [0.0, 0.25, 0.5, 0.75, 1.0]
METHODS_WITH_ALPHA = ["meth1"]
METHODS_WITHOUT_ALPHA = ["avgconf", "maxconf", "maxconfa"]
ALL_METHODS = METHODS_WITH_ALPHA + METHODS_WITHOUT_ALPHA


def run_cmd(cmd):
    """Run a shell command and return stdout, stderr, returncode."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.stdout, result.stderr, result.returncode


def parse_sys_file(sys_file_path):
    """Parse a sclite .sys summary file extracting WER, per-speaker WER, NCE.

    The summary table format is:
      | SPKR | # Snt # Wrd | Corr Sub Del Ins Err S.Err |
    When confidence scores are present, an extra NCE column appears:
      | SPKR | # Snt # Wrd | Corr Sub Del Ins Err S.Err | NCE |

    Returns dict with 'overall_wer', 'speaker_wer' (dict), 'nce'.
    """
    metrics = {"overall_wer": None, "speaker_wer": {}, "nce": None}
    if not os.path.exists(sys_file_path):
        return metrics
    with open(sys_file_path) as f:
        content = f.read()

    for line in content.split('\n'):
        if '|' not in line:
            continue
        if 'SPKR' in line or '---' in line or '===' in line:
            continue

        parts = line.split('|')
        is_sum = 'Sum' in line

        # Extract speaker name from non-Sum lines
        speaker = None
        if not is_sum and len(parts) >= 2:
            s = parts[1].strip()
            if s and len(s) > 0 and s[0].isalpha():
                speaker = s

        # Parse each pipe-delimited section
        wer_val = None
        nce_val = None
        for part in parts:
            nums = part.strip().split()
            if len(nums) == 6:
                try:
                    w = float(nums[4])
                    if 0 <= w <= 100:
                        wer_val = w
                except ValueError:
                    pass
            elif len(nums) == 1:
                try:
                    n = float(nums[0])
                    if -2.0 <= n <= 2.0:
                        nce_val = n
                except ValueError:
                    pass

        if is_sum:
            metrics["overall_wer"] = wer_val
            metrics["nce"] = nce_val
        elif speaker and wer_val is not None:
            metrics["speaker_wer"][speaker] = wer_val

    return metrics


def score_ctm(ctm_file, output_name):
    """Score a CTM file against the reference using sclite, return metrics."""
    os.makedirs(WORK_DIR, exist_ok=True)
    cmd = [
        "sclite",
        "-r", REF_FILE, "stm",
        "-h", ctm_file, "ctm",
        "-o", "sum",
        "-O", WORK_DIR,
        "-n", output_name,
        "-f", "0"
    ]
    run_cmd(cmd)
    sys_file = os.path.join(WORK_DIR, "{}.sys".format(output_name))
    return parse_sys_file(sys_file)


def run_rover(system_names, voting_method, alpha, output_name):
    """Run ROVER on a combination of systems with given method and alpha."""
    os.makedirs(WORK_DIR, exist_ok=True)
    cmd = ["rover"]
    for sys_name in system_names:
        cmd.extend(["-h", os.path.join(DATA_DIR, "{}.ctm".format(sys_name)), "ctm"])
    output_ctm = os.path.join(WORK_DIR, "{}.ctm".format(output_name))
    cmd.extend(["-o", output_ctm, "-m", voting_method, "-a", str(alpha), "-f", "0"])
    run_cmd(cmd)
    return output_ctm if os.path.exists(output_ctm) else None


def test_results_file_exists():
    """Results file must exist."""
    assert os.path.exists(RESULTS_FILE), \
        "Results file not found at {}".format(RESULTS_FILE)


def test_results_structure():
    """Results must have the required keys with correct types."""
    with open(RESULTS_FILE) as f:
        data = json.load(f)

    assert "per_system" in data, "Missing 'per_system'"
    assert "calibration_ranking" in data, "Missing 'calibration_ranking'"
    assert "rover_optimization" in data, "Missing 'rover_optimization'"

    # per_system structure
    ps = data["per_system"]
    for sys_name in SYSTEMS:
        assert sys_name in ps, "Missing per_system.{}".format(sys_name)
        s = ps[sys_name]
        assert "wer" in s, "Missing wer for {}".format(sys_name)
        assert "nce" in s, "Missing nce for {}".format(sys_name)
        assert "speaker_wer" in s, "Missing speaker_wer for {}".format(sys_name)
        assert isinstance(s["wer"], (int, float)), \
            "wer for {} must be numeric".format(sys_name)
        assert isinstance(s["nce"], (int, float)), \
            "nce for {} must be numeric".format(sys_name)
        sw = s["speaker_wer"]
        assert isinstance(sw, dict), "speaker_wer must be a dict"
        for spk in SPEAKERS:
            assert spk in sw, \
                "Missing speaker {} in {}.speaker_wer".format(spk, sys_name)
            assert isinstance(sw[spk], (int, float)), \
                "speaker_wer.{} for {} must be numeric".format(spk, sys_name)

    # calibration_ranking structure
    cr = data["calibration_ranking"]
    assert isinstance(cr, list) and len(cr) == 4, \
        "calibration_ranking must be a list of 4 systems"
    assert set(cr) == set(SYSTEMS), \
        "calibration_ranking must contain all 4 systems exactly once"

    # rover_optimization structure
    ro = data["rover_optimization"]
    assert "best_config" in ro, "Missing rover_optimization.best_config"
    assert "search_log" in ro, "Missing rover_optimization.search_log"

    bc = ro["best_config"]
    assert isinstance(bc["systems"], list) and len(bc["systems"]) >= 2, \
        "best_config.systems must be a list of >= 2 systems"
    for s in bc["systems"]:
        assert s in SYSTEMS, "Unknown system in best_config: {}".format(s)
    assert isinstance(bc["method"], str) and len(bc["method"]) > 0, \
        "best_config.method must be a non-empty string"
    assert isinstance(bc["alpha"], (int, float)), \
        "best_config.alpha must be numeric"
    assert 0.0 <= bc["alpha"] <= 1.0, \
        "best_config.alpha must be in [0, 1]"
    assert isinstance(bc["wer"], (int, float)), \
        "best_config.wer must be numeric"

    sl = ro["search_log"]
    assert isinstance(sl, list) and len(sl) >= 44, \
        "search_log should have >= 44 entries (comprehensive search), got {}".format(len(sl))

    # Verify the search explored multiple methods and alpha values
    methods_used = set(e["method"] for e in sl)
    alpha_values_used = set(round(e["alpha"], 2) for e in sl)
    assert len(methods_used) >= 3, \
        "Search must cover >= 3 voting methods, found: {}".format(methods_used)
    assert len(alpha_values_used) >= 3, \
        "Search must cover >= 3 distinct alpha values, found: {}".format(alpha_values_used)

    for entry in sl:
        assert "systems" in entry and "method" in entry \
            and "alpha" in entry and "wer" in entry, \
            "Each search_log entry needs systems, method, alpha, wer"


def test_individual_wer_values():
    """Individual system WER values must match sclite output."""
    with open(RESULTS_FILE) as f:
        data = json.load(f)

    for sys_name in SYSTEMS:
        ctm_file = os.path.join(DATA_DIR, "{}.ctm".format(sys_name))
        metrics = score_ctm(ctm_file, "vfy_wer_{}".format(sys_name))
        assert metrics["overall_wer"] is not None, \
            "Failed to compute WER for {}".format(sys_name)
        claimed = data["per_system"][sys_name]["wer"]
        diff = abs(metrics["overall_wer"] - claimed)
        assert diff <= WER_TOLERANCE, \
            "{}: claimed WER={}, actual={}, diff={}".format(
                sys_name, claimed, metrics["overall_wer"], diff)


def test_speaker_wer_values():
    """Per-speaker WER values must match sclite output."""
    with open(RESULTS_FILE) as f:
        data = json.load(f)

    for sys_name in SYSTEMS:
        ctm_file = os.path.join(DATA_DIR, "{}.ctm".format(sys_name))
        metrics = score_ctm(ctm_file, "vfy_spk_{}".format(sys_name))
        assert len(metrics["speaker_wer"]) > 0, \
            "No per-speaker WER from sclite for {}".format(sys_name)
        for spk, expected_wer in metrics["speaker_wer"].items():
            if spk in data["per_system"][sys_name]["speaker_wer"]:
                claimed = data["per_system"][sys_name]["speaker_wer"][spk]
                diff = abs(expected_wer - claimed)
                assert diff <= WER_TOLERANCE, \
                    "{} speaker {}: claimed={}, actual={}, diff={}".format(
                        sys_name, spk, claimed, expected_wer, diff)


def test_nce_values():
    """NCE values must match sclite confidence calibration output."""
    with open(RESULTS_FILE) as f:
        data = json.load(f)

    for sys_name in SYSTEMS:
        ctm_file = os.path.join(DATA_DIR, "{}.ctm".format(sys_name))
        metrics = score_ctm(ctm_file, "vfy_nce_{}".format(sys_name))
        claimed = data["per_system"][sys_name]["nce"]
        if metrics["nce"] is not None:
            diff = abs(metrics["nce"] - claimed)
            assert diff <= NCE_TOLERANCE, \
                "{}: claimed NCE={}, actual={}, diff={}".format(
                    sys_name, claimed, metrics["nce"], diff)
        else:
            assert -2.0 <= claimed <= 2.0, \
                "{}: NCE={} out of reasonable range".format(sys_name, claimed)


def test_calibration_ranking():
    """Calibration ranking must match actual NCE ordering (descending)."""
    with open(RESULTS_FILE) as f:
        data = json.load(f)

    nce_values = {}
    for sys_name in SYSTEMS:
        ctm_file = os.path.join(DATA_DIR, "{}.ctm".format(sys_name))
        metrics = score_ctm(ctm_file, "vfy_cal_{}".format(sys_name))
        nce_values[sys_name] = metrics["nce"]

    valid_nce = {k: v for k, v in nce_values.items() if v is not None}
    if len(valid_nce) == 4:
        expected_ranking = sorted(
            valid_nce.keys(), key=lambda x: valid_nce[x], reverse=True)
        claimed_ranking = data["calibration_ranking"]
        assert claimed_ranking == expected_ranking, \
            "Calibration ranking mismatch: claimed={}, expected={} (NCE values: {})".format(
                claimed_ranking, expected_ranking, valid_nce)


def test_best_config_wer():
    """The claimed best ROVER configuration must produce the claimed WER."""
    with open(RESULTS_FILE) as f:
        data = json.load(f)

    bc = data["rover_optimization"]["best_config"]
    combo_name = "vfy_best_{}_{}_{:.2f}".format(
        "_".join(sorted(bc["systems"])), bc["method"], bc["alpha"])
    rover_ctm = run_rover(bc["systems"], bc["method"], bc["alpha"], combo_name)
    assert rover_ctm is not None, \
        "ROVER failed for claimed best config: {} {} alpha={}".format(
            bc["systems"], bc["method"], bc["alpha"])

    metrics = score_ctm(rover_ctm, combo_name + "_score")
    assert metrics["overall_wer"] is not None, \
        "Failed to score ROVER output for best configuration"
    diff = abs(metrics["overall_wer"] - bc["wer"])
    assert diff <= WER_TOLERANCE, \
        "Best config WER mismatch: claimed={}, actual={}, diff={}".format(
            bc["wer"], metrics["overall_wer"], diff)


def test_best_is_actually_optimal():
    """No other ROVER configuration should produce a significantly lower WER.

    Exhaustively searches across methods, alpha values, and system subsets
    to verify the claimed best is truly optimal.
    """
    with open(RESULTS_FILE) as f:
        data = json.load(f)

    claimed_best_wer = data["rover_optimization"]["best_config"]["wer"]

    for size in range(2, len(SYSTEMS) + 1):
        for combo in combinations(SYSTEMS, size):
            # Test methods that don't use alpha (use default 1.0)
            for method in METHODS_WITHOUT_ALPHA:
                combo_name = "optchk_{}_{}".format(
                    "_".join(combo), method)
                rover_ctm = run_rover(list(combo), method, 1.0, combo_name)
                if rover_ctm is None:
                    continue
                metrics = score_ctm(rover_ctm, combo_name + "_s")
                if metrics["overall_wer"] is None:
                    continue
                assert metrics["overall_wer"] >= claimed_best_wer - WER_TOLERANCE, \
                    "Found better: {} {} WER={} < claimed_best={}".format(
                        combo, method, metrics["overall_wer"], claimed_best_wer)

            # Test meth1 with alpha sweep
            for alpha in ALPHA_VALUES:
                combo_name = "optchk_{}_meth1_a{:.2f}".format(
                    "_".join(combo), alpha)
                rover_ctm = run_rover(list(combo), "meth1", alpha, combo_name)
                if rover_ctm is None:
                    continue
                metrics = score_ctm(rover_ctm, combo_name + "_s")
                if metrics["overall_wer"] is None:
                    continue
                assert metrics["overall_wer"] >= claimed_best_wer - WER_TOLERANCE, \
                    "Found better: {} meth1 alpha={} WER={} < claimed_best={}".format(
                        combo, alpha, metrics["overall_wer"], claimed_best_wer)


def test_wer_values_reasonable():
    """WER values should be in a reasonable range for ASR systems."""
    with open(RESULTS_FILE) as f:
        data = json.load(f)

    for sys_name in SYSTEMS:
        wer = data["per_system"][sys_name]["wer"]
        assert 0 <= wer <= 100, \
            "{} WER={} out of range".format(sys_name, wer)
        for spk, spk_wer in data["per_system"][sys_name]["speaker_wer"].items():
            assert 0 <= spk_wer <= 100, \
                "{} {} WER={} out of range".format(sys_name, spk, spk_wer)

    assert 0 <= data["rover_optimization"]["best_config"]["wer"] <= 100
    best_individual = min(
        data["per_system"][s]["wer"] for s in SYSTEMS)
    assert data["rover_optimization"]["best_config"]["wer"] <= best_individual + WER_TOLERANCE, \
        "ROVER combination should not be worse than best individual system"


def test_nce_sign_consistency():
    """Verify NCE signs are consistent with calibration quality.

    Systems with anti-correlated confidence (high conf on errors)
    should have negative NCE. Well-calibrated systems should have
    positive NCE.
    """
    with open(RESULTS_FILE) as f:
        data = json.load(f)

    nce_values = {s: data["per_system"][s]["nce"] for s in SYSTEMS}

    # At least one system should have positive NCE (well-calibrated)
    assert any(v > 0 for v in nce_values.values()), \
        "No system has positive NCE — data or parsing error"

    # The systems should have meaningfully different NCE values
    nce_range = max(nce_values.values()) - min(nce_values.values())
    assert nce_range > 0.1, \
        "NCE range too narrow ({}), expected diverse calibration".format(nce_range)
