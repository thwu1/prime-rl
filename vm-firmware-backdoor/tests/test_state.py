
import json
import os
import subprocess

# Expected values (deterministic from gen_firmware.py)
ALPHA_LEGIT_TOKEN = "a37f22b844e915cc"
ALPHA_EXPLOIT_TOKEN = "bbaa000000000000"
BETA_EXPLOIT_TOKEN = "3b100388cb801378"
GAMMA_LEGIT_TOKEN = "c73a915de26f48b6"

ALPHA_VALID_CWES = {"CWE-912", "CWE-506"}
BETA_VALID_CWES = {"CWE-330", "CWE-338"}
GAMMA_VALID_CWES = {"CWE-328", "CWE-327"}


def run_vm(firmware, token):
    r = subprocess.run(
        ["/app/ooovm", firmware],
        input=token.encode(),
        capture_output=True,
        timeout=10,
    )
    return r.stdout.decode()


def load_audit():
    with open("/app/audit.json") as f:
        return json.load(f)


# ---------- audit.json existence and schema ----------

def test_audit_json_exists():
    assert os.path.exists("/app/audit.json"), "audit.json not found"


def test_audit_json_schema():
    audit = load_audit()
    for key in ("alpha", "beta", "gamma", "risk_ranking", "ranking_justification"):
        assert key in audit, f"Missing top-level key: {key}"
    for fw in ("alpha", "beta", "gamma"):
        for field in ("vulnerability_class", "cwe", "exploit_token", "root_cause",
                      "cvss_vector", "cvss_score"):
            assert field in audit[fw], f"Missing {fw}.{field}"


# ---------- exploit token verification ----------

def test_alpha_exploit_authenticates():
    """Solver's alpha exploit token must produce AUTHENTICATED."""
    audit = load_audit()
    token = audit["alpha"]["exploit_token"]
    out = run_vm("/app/auth_alpha.bin", token)
    assert "AUTHENTICATED" in out, f"Alpha exploit failed: {out}"


def test_beta_exploit_authenticates():
    """Solver's beta exploit token must produce AUTHENTICATED."""
    audit = load_audit()
    token = audit["beta"]["exploit_token"]
    out = run_vm("/app/auth_beta.bin", token)
    assert "AUTHENTICATED" in out, f"Beta exploit failed: {out}"


def test_gamma_exploit_authenticates():
    """Solver's gamma exploit token must produce AUTHENTICATED."""
    audit = load_audit()
    token = audit["gamma"]["exploit_token"]
    out = run_vm("/app/auth_gamma.bin", token)
    assert "AUTHENTICATED" in out, f"Gamma exploit failed: {out}"


def test_gamma_exploit_is_collision():
    """Gamma exploit must be different from the legitimate key (a true collision)."""
    audit = load_audit()
    assert audit["gamma"]["exploit_token"] != GAMMA_LEGIT_TOKEN, (
        "Gamma exploit must be a hash collision, not the legitimate key itself"
    )


# ---------- vulnerability classification ----------

def test_alpha_cwe_classification():
    """Alpha firmware must be classified with the correct CWE."""
    audit = load_audit()
    assert audit["alpha"]["cwe"] in ALPHA_VALID_CWES, (
        f"Expected one of {ALPHA_VALID_CWES}, got {audit['alpha']['cwe']}"
    )


def test_beta_cwe_classification():
    """Beta firmware must be classified with the correct CWE."""
    audit = load_audit()
    assert audit["beta"]["cwe"] in BETA_VALID_CWES, (
        f"Expected one of {BETA_VALID_CWES}, got {audit['beta']['cwe']}"
    )


def test_gamma_cwe_classification():
    """Gamma firmware must be classified with the correct CWE."""
    audit = load_audit()
    assert audit["gamma"]["cwe"] in GAMMA_VALID_CWES, (
        f"Expected one of {GAMMA_VALID_CWES}, got {audit['gamma']['cwe']}"
    )


# ---------- CVSS evaluation ----------

def test_cvss_vectors_valid_format():
    """All CVSS vectors must be valid CVSS 3.1 format with all base metrics."""
    audit = load_audit()
    required_metrics = {"AV", "AC", "PR", "UI", "S", "C", "I", "A"}
    for fw in ("alpha", "beta", "gamma"):
        vec = audit[fw]["cvss_vector"]
        assert vec.startswith("CVSS:3.1/"), (
            f"{fw} CVSS vector must start with 'CVSS:3.1/', got '{vec}'"
        )
        parts = vec.split("/")[1:]  # skip "CVSS:3.1"
        metrics = {p.split(":")[0] for p in parts}
        missing = required_metrics - metrics
        assert not missing, f"{fw} CVSS vector missing metrics: {missing}"


def test_cvss_scores_valid_range():
    """All CVSS scores must be valid numbers in [0.0, 10.0]."""
    audit = load_audit()
    for fw in ("alpha", "beta", "gamma"):
        score = audit[fw]["cvss_score"]
        assert isinstance(score, (int, float)), f"{fw} score must be numeric"
        assert 0.0 <= score <= 10.0, f"{fw} score {score} out of range [0, 10]"


def test_alpha_cvss_is_critical():
    """Alpha (backdoor) should be rated critical severity (CVSS >= 9.0)."""
    audit = load_audit()
    assert audit["alpha"]["cvss_score"] >= 9.0, (
        f"Alpha backdoor should be critical (>= 9.0), got {audit['alpha']['cvss_score']}"
    )


# ---------- risk ranking ----------

def test_risk_ranking_structure():
    """Risk ranking must be a 3-element list containing all firmware names."""
    audit = load_audit()
    ranking = audit["risk_ranking"]
    assert isinstance(ranking, list), "risk_ranking must be a list"
    assert len(ranking) == 3, f"risk_ranking must have 3 elements, got {len(ranking)}"
    assert set(ranking) == {"alpha", "beta", "gamma"}, (
        f"risk_ranking must contain exactly alpha, beta, gamma; got {ranking}"
    )


def test_risk_ranking_alpha_most_critical():
    """Alpha (backdoor/intentional compromise) must be ranked most critical."""
    audit = load_audit()
    assert audit["risk_ranking"][0] == "alpha", (
        f"Alpha should be ranked most critical, got {audit['risk_ranking'][0]}"
    )


# ---------- alpha binary patch verification ----------

def test_alpha_patch_file_exists():
    assert os.path.exists("/app/auth_alpha_patched.bin"), "Patched alpha firmware not found"


def test_alpha_patch_valid_header():
    with open("/app/auth_alpha_patched.bin", "rb") as f:
        data = f.read()
    assert data[:4] == b"OOOV", "Patched alpha firmware must have valid OOOV header"


def test_alpha_patch_same_size():
    orig = os.path.getsize("/app/auth_alpha.bin")
    patched = os.path.getsize("/app/auth_alpha_patched.bin")
    assert patched == orig, f"Alpha patch changed size: {orig} -> {patched}"


def test_alpha_patch_accepts_legit_token():
    """Patched alpha firmware must still authenticate with the legitimate key."""
    out = run_vm("/app/auth_alpha_patched.bin", ALPHA_LEGIT_TOKEN)
    assert "AUTHENTICATED" in out, f"Alpha patch broke legit auth: {out}"


def test_alpha_patch_rejects_exploit():
    """Patched alpha firmware must reject the backdoor exploit token."""
    out = run_vm("/app/auth_alpha_patched.bin", ALPHA_EXPLOIT_TOKEN)
    assert "DENIED" in out, f"Alpha patch did not fix backdoor: {out}"


def test_alpha_patch_rejects_random():
    """Patched alpha firmware must reject arbitrary tokens."""
    out = run_vm("/app/auth_alpha_patched.bin", "0000000000000000")
    assert "DENIED" in out, f"Alpha patch accepts garbage: {out}"


# ---------- gamma patch verification ----------

def test_gamma_patch_file_exists():
    assert os.path.exists("/app/auth_gamma_patched.bin"), "Patched gamma firmware not found"


def test_gamma_patch_valid_header():
    with open("/app/auth_gamma_patched.bin", "rb") as f:
        data = f.read()
    assert data[:4] == b"OOOV", "Patched gamma firmware must have valid OOOV header"


def test_gamma_patch_accepts_legit_token():
    """Patched gamma firmware must authenticate with the legitimate key."""
    out = run_vm("/app/auth_gamma_patched.bin", GAMMA_LEGIT_TOKEN)
    assert "AUTHENTICATED" in out, f"Gamma patch broke legit auth: {out}"


def test_gamma_patch_rejects_exploit():
    """Patched gamma firmware must reject the checksum collision exploit."""
    audit = load_audit()
    exploit = audit["gamma"]["exploit_token"]
    out = run_vm("/app/auth_gamma_patched.bin", exploit)
    assert "DENIED" in out, f"Gamma patch still accepts collision exploit: {out}"


def test_gamma_patch_rejects_random():
    """Patched gamma firmware must reject arbitrary tokens."""
    out = run_vm("/app/auth_gamma_patched.bin", "0000000000000000")
    assert "DENIED" in out, f"Gamma patch accepts garbage: {out}"
