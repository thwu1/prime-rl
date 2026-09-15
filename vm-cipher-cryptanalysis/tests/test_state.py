
import json
import os
import subprocess


EXPECTED_FLAG = "OOO{f31st3l_prng_w34k_s33d}"
FORGERY_TARGET = b"SECURITY_AUDIT_COMPLETE:VERIFIED"


# ---- Assessment structure tests ----

def test_assessment_file_exists():
    """Assessment file must exist at /app/assessment.json."""
    assert os.path.isfile("/app/assessment.json"), "/app/assessment.json does not exist"


def test_assessment_structure():
    """Assessment must contain verdict, justification, attack_complexity, risk_level for each session."""
    with open("/app/assessment.json") as f:
        data = json.load(f)
    for session in ["alpha", "beta", "gamma"]:
        assert session in data, f"Missing session '{session}' in assessment"
        for field in ["verdict", "justification", "attack_complexity", "risk_level"]:
            assert field in data[session], f"Missing '{field}' for {session}"
        assert data[session]["verdict"] in ("recoverable", "not_recoverable"), \
            f"Invalid verdict for {session}: {data[session]['verdict']}"
        assert len(data[session]["justification"]) >= 20, \
            f"Justification for {session} is too short to be meaningful"
        assert isinstance(data[session]["attack_complexity"], str) and \
            len(data[session]["attack_complexity"]) >= 15, \
            f"attack_complexity for {session} must be a descriptive string"
        rl = data[session]["risk_level"]
        assert isinstance(rl, int) and 1 <= rl <= 5, \
            f"risk_level for {session} must be int 1-5, got {rl}"


# ---- Verdict correctness tests ----

def test_assessment_verdicts_correct():
    """Verdicts must correctly classify each session's recoverability."""
    with open("/app/assessment.json") as f:
        data = json.load(f)
    assert data["alpha"]["verdict"] == "recoverable", \
        f"Alpha should be recoverable, got: {data['alpha']['verdict']}"
    assert data["beta"]["verdict"] == "not_recoverable", \
        f"Beta should be not_recoverable, got: {data['beta']['verdict']}"
    assert data["gamma"]["verdict"] == "recoverable", \
        f"Gamma should be recoverable, got: {data['gamma']['verdict']}"


# ---- Risk level evaluation tests (evaluate-level: comparative judgment) ----

def test_risk_levels_reflect_relative_exploitability():
    """Risk levels must correctly rank sessions by exploitability."""
    with open("/app/assessment.json") as f:
        data = json.load(f)
    alpha_rl = data["alpha"]["risk_level"]
    beta_rl = data["beta"]["risk_level"]
    gamma_rl = data["gamma"]["risk_level"]
    # Alpha: time-seeded with ~100s window -> critical risk
    assert alpha_rl >= 4, \
        f"Alpha risk should be >= 4 (trivially brute-forceable), got {alpha_rl}"
    # Beta: hardware RNG, full entropy -> negligible risk
    assert beta_rl <= 2, \
        f"Beta risk should be <= 2 (hardware RNG), got {beta_rl}"
    # Gamma: derived from alpha -> high risk once alpha is compromised
    assert gamma_rl >= 3, \
        f"Gamma risk should be >= 3 (derived from compromised session), got {gamma_rl}"
    # Relative ordering: alpha >= gamma > beta
    assert alpha_rl >= gamma_rl, \
        f"Alpha ({alpha_rl}) should be at least as risky as gamma ({gamma_rl})"
    assert gamma_rl > beta_rl, \
        f"Gamma ({gamma_rl}) should be riskier than beta ({beta_rl})"


# ---- Justification quality tests (evaluate-level: grounded reasoning) ----

def test_alpha_justification_demonstrates_understanding():
    """Alpha justification must reference the time-based key weakness."""
    with open("/app/assessment.json") as f:
        data = json.load(f)
    j = data["alpha"]["justification"].lower()
    time_keywords = ["time", "timestamp", "seed", "brute", "clock", "window", "epoch"]
    assert any(kw in j for kw in time_keywords), \
        f"Alpha justification lacks evidence of understanding the time-seed vulnerability: {j}"


def test_beta_justification_demonstrates_understanding():
    """Beta justification must reference the hardware entropy source."""
    with open("/app/assessment.json") as f:
        data = json.load(f)
    j = data["beta"]["justification"].lower()
    hw_keywords = ["hardware", "random", "entropy", "rng", "unpredictable", "infeasible",
                   "hsm", "module"]
    assert any(kw in j for kw in hw_keywords), \
        f"Beta justification lacks evidence of understanding hardware RNG security: {j}"


def test_gamma_justification_demonstrates_understanding():
    """Gamma justification must reference the derived-key dependency."""
    with open("/app/assessment.json") as f:
        data = json.load(f)
    j = data["gamma"]["justification"].lower()
    dep_keywords = ["derived", "dependent", "relationship", "transform", "primary",
                    "xor", "alpha", "alternate", "flag"]
    assert any(kw in j for kw in dep_keywords), \
        f"Gamma justification lacks evidence of understanding the derived-key relationship: {j}"


# ---- Flag tests ----

def test_flag_file_exists():
    """Flag file must exist at /app/flag.txt."""
    assert os.path.isfile("/app/flag.txt"), "/app/flag.txt does not exist"


def test_flag_content():
    """Flag file must contain the correct decrypted and combined flag."""
    with open("/app/flag.txt", "r") as f:
        flag = f.read().strip()
    assert flag == EXPECTED_FLAG, f"Wrong flag: got '{flag}'"


def test_flag_format():
    """Flag must follow the OOO{{...}} format."""
    with open("/app/flag.txt", "r") as f:
        flag = f.read().strip()
    assert flag.startswith("OOO{"), f"Flag does not start with OOO{{: '{flag}'"
    assert flag.endswith("}"), f"Flag does not end with }}: '{flag}'"


# ---- Forgery tests (create-level: novel artifact construction) ----

def test_forgery_file_exists():
    """Forgery ciphertext must exist at /app/forgery.enc."""
    assert os.path.isfile("/app/forgery.enc"), "/app/forgery.enc does not exist"


def test_forgery_is_block_aligned():
    """Forgery ciphertext must be block-aligned (multiple of 8 bytes)."""
    size = os.path.getsize("/app/forgery.enc")
    assert size > 0, "Forgery file is empty"
    assert size % 8 == 0, f"Forgery size {size} is not a multiple of 8 (block size)"


def test_forgery_decrypts_to_target():
    """Forgery must decrypt to exact target string using the binary with seed 1337."""
    result = subprocess.run(
        ['/app/cipher_engine', 'd', '1337', '/app/forgery.enc', '/tmp/forgery_check.dec'],
        capture_output=True, timeout=10
    )
    assert result.returncode == 0, \
        f"Binary decryption failed with rc={result.returncode}: {result.stderr.decode()}"
    with open('/tmp/forgery_check.dec', 'rb') as f:
        content = f.read()
    assert content == FORGERY_TARGET, \
        f"Forgery decrypted to {content!r}, expected {FORGERY_TARGET!r}"
