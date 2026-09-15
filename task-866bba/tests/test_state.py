
import json
import os
import subprocess

SIGNERS = ["engineering", "security", "release"]
TAMPERED = "data-pipeline.bin"

# Policy-derived expected signature bundles
REQUIRED_SIGNATURES = {
    "api-server.bin": ["engineering"],
    "auth-module.bin": ["engineering", "security"],
    "data-pipeline.bin": ["engineering"],
    "crypto-lib.bin": ["engineering", "security", "release"],
    "monitoring-agent.bin": ["engineering", "release"],
}

# Policy-derived expected attestation pairs (type, signer)
REQUIRED_ATTESTATIONS = {
    "api-server.bin": [("slsaprovenance", "engineering")],
    "auth-module.bin": [("slsaprovenance", "engineering"), ("vuln", "security")],
    "data-pipeline.bin": [("slsaprovenance", "engineering")],
    "crypto-lib.bin": [("slsaprovenance", "engineering"), ("vuln", "security")],
    "monitoring-agent.bin": [("slsaprovenance", "engineering")],
}


def test_cosign_installed():
    """cosign binary must be available."""
    result = subprocess.run(["cosign", "version"], capture_output=True)
    assert result.returncode == 0, "cosign is not installed or not in PATH"


def test_key_pairs_exist():
    """All three team key pairs must exist with valid PEM public keys."""
    for signer in SIGNERS:
        key_path = f"/app/keys/{signer}.key"
        pub_path = f"/app/keys/{signer}.pub"
        assert os.path.exists(key_path), f"Missing private key: {key_path}"
        assert os.path.exists(pub_path), f"Missing public key: {pub_path}"
        with open(pub_path, "r") as f:
            content = f.read()
        assert "PUBLIC KEY" in content, f"{pub_path} does not contain a valid public key"


def test_signature_bundles_exist_and_valid():
    """All required signature bundle files must exist and be valid JSON."""
    for artifact, signers in REQUIRED_SIGNATURES.items():
        for signer in signers:
            bundle_path = f"/app/bundles/{artifact}.{signer}.bundle"
            assert os.path.exists(bundle_path), f"Missing signature bundle: {bundle_path}"
            with open(bundle_path, "r") as f:
                data = json.load(f)
            assert isinstance(data, dict), f"Bundle {bundle_path} is not a JSON object"
            has_old = "base64Signature" in data
            has_new = "mediaType" in data
            assert has_old or has_new, (
                f"Bundle {bundle_path} missing signature data. Keys: {list(data.keys())}"
            )


def test_signature_verification_non_tampered():
    """cosign verify-blob must succeed for all non-tampered deployed artifacts."""
    env = os.environ.copy()
    env["COSIGN_PASSWORD"] = ""
    for artifact, signers in REQUIRED_SIGNATURES.items():
        if artifact == TAMPERED:
            continue
        for signer in signers:
            result = subprocess.run(
                [
                    "cosign", "verify-blob",
                    "--key", f"/app/keys/{signer}.pub",
                    "--bundle", f"/app/bundles/{artifact}.{signer}.bundle",
                    "--insecure-ignore-tlog",
                    f"/app/artifacts/{artifact}",
                ],
                capture_output=True,
                env=env,
            )
            assert result.returncode == 0, (
                f"Signature verification failed for {artifact} with {signer}: "
                f"{result.stderr.decode()}"
            )


def test_tampered_artifact_signature_fails():
    """cosign verify-blob must fail for the tampered deployed artifact."""
    env = os.environ.copy()
    env["COSIGN_PASSWORD"] = ""
    for signer in REQUIRED_SIGNATURES[TAMPERED]:
        result = subprocess.run(
            [
                "cosign", "verify-blob",
                "--key", f"/app/keys/{signer}.pub",
                "--bundle", f"/app/bundles/{TAMPERED}.{signer}.bundle",
                "--insecure-ignore-tlog",
                f"/app/artifacts/{TAMPERED}",
            ],
            capture_output=True,
            env=env,
        )
        assert result.returncode != 0, (
            f"Verification SHOULD HAVE FAILED for tampered {TAMPERED} "
            f"with {signer} key but succeeded"
        )


def test_attestation_statements_exist():
    """All required attestation statement files must exist with valid in-toto structure."""
    for artifact, attestations in REQUIRED_ATTESTATIONS.items():
        for att_type, _signer in attestations:
            path = f"/app/attestations/{artifact}.{att_type}.statement"
            assert os.path.exists(path), f"Missing attestation statement: {path}"
            with open(path, "r") as f:
                data = json.load(f)
            assert data.get("_type") == "https://in-toto.io/Statement/v0.1", (
                f"Statement {path} has wrong _type: {data.get('_type')}"
            )
            assert "subject" in data, f"Statement {path} missing 'subject'"
            assert len(data["subject"]) > 0, f"Statement {path} has empty subject"
            assert "digest" in data["subject"][0], f"Statement {path} subject missing digest"
            assert "sha256" in data["subject"][0]["digest"], (
                f"Statement {path} subject missing sha256 digest"
            )
            assert "predicateType" in data, f"Statement {path} missing predicateType"
            assert "predicate" in data, f"Statement {path} missing predicate"


def test_attestation_predicate_types():
    """Attestation predicateType URIs must conform to established specifications."""
    for artifact, attestations in REQUIRED_ATTESTATIONS.items():
        for att_type, _signer in attestations:
            path = f"/app/attestations/{artifact}.{att_type}.statement"
            with open(path, "r") as f:
                data = json.load(f)
            pred_uri = data.get("predicateType", "")
            if att_type == "slsaprovenance":
                assert "slsa.dev/provenance" in pred_uri, (
                    f"SLSA provenance attestation in {path} has wrong predicateType "
                    f"'{pred_uri}' — expected URI containing 'slsa.dev/provenance'"
                )
            elif att_type == "vuln":
                assert "vuln" in pred_uri.lower(), (
                    f"Vulnerability attestation in {path} has wrong predicateType "
                    f"'{pred_uri}' — expected URI referencing vulnerability scanning"
                )


def test_attestation_predicate_content():
    """Attestation predicates must contain spec-conformant content."""
    for artifact, attestations in REQUIRED_ATTESTATIONS.items():
        for att_type, _signer in attestations:
            path = f"/app/attestations/{artifact}.{att_type}.statement"
            with open(path, "r") as f:
                data = json.load(f)
            predicate = data.get("predicate", {})
            assert len(predicate) > 0, (
                f"Statement {path} has empty predicate"
            )
            if att_type == "slsaprovenance":
                assert "builder" in predicate or "buildDefinition" in predicate, (
                    f"SLSA provenance predicate in {path} missing builder/buildDefinition — "
                    f"does not conform to SLSA provenance spec"
                )
            elif att_type == "vuln":
                assert "scanner" in predicate, (
                    f"Vulnerability scan predicate in {path} missing scanner metadata"
                )


def test_attestation_bundles_exist_and_valid():
    """All required attestation signature bundle files must exist and be valid JSON."""
    for artifact, attestations in REQUIRED_ATTESTATIONS.items():
        for att_type, _signer in attestations:
            path = f"/app/attestations/{artifact}.{att_type}.bundle"
            assert os.path.exists(path), f"Missing attestation bundle: {path}"
            with open(path, "r") as f:
                data = json.load(f)
            assert isinstance(data, dict), f"Attestation bundle {path} is not a JSON object"


def test_attestation_signature_verification_non_tampered():
    """cosign verify-blob on attestation statements must succeed for non-tampered artifacts."""
    env = os.environ.copy()
    env["COSIGN_PASSWORD"] = ""
    for artifact, attestations in REQUIRED_ATTESTATIONS.items():
        if artifact == TAMPERED:
            continue
        for att_type, signer in attestations:
            result = subprocess.run(
                [
                    "cosign", "verify-blob",
                    "--key", f"/app/keys/{signer}.pub",
                    "--bundle", f"/app/attestations/{artifact}.{att_type}.bundle",
                    "--insecure-ignore-tlog",
                    f"/app/attestations/{artifact}.{att_type}.statement",
                ],
                capture_output=True,
                env=env,
            )
            assert result.returncode == 0, (
                f"Attestation sig verification failed for {artifact}/{att_type}: "
                f"{result.stderr.decode()}"
            )


def test_audit_report_exists_and_valid():
    """Audit report must exist at /app/audit_report.json with correct structure."""
    assert os.path.exists("/app/audit_report.json"), "audit_report.json not found"
    with open("/app/audit_report.json", "r") as f:
        report = json.load(f)
    assert "artifacts" in report, "audit_report.json missing 'artifacts' key"
    assert "summary" in report, "audit_report.json missing 'summary' key"
    assert isinstance(report["artifacts"], list), "'artifacts' must be a list"
    assert len(report["artifacts"]) == 5, (
        f"Expected 5 artifacts in report, got {len(report['artifacts'])}"
    )


def test_audit_report_summary():
    """Audit report summary must reflect correct totals with at least 1 failure."""
    with open("/app/audit_report.json", "r") as f:
        report = json.load(f)
    summary = report["summary"]
    assert summary["total"] == 5, f"Expected total=5, got {summary['total']}"
    assert summary["failed"] >= 1, (
        f"Expected at least 1 failed artifact, got {summary['failed']}"
    )
    assert summary["passed"] + summary["failed"] == summary["total"], (
        "passed + failed must equal total"
    )


def test_audit_report_tampered_detected():
    """The tampered artifact must be marked as 'fail' in the audit report."""
    with open("/app/audit_report.json", "r") as f:
        report = json.load(f)
    tampered_entry = next(
        (e for e in report["artifacts"] if TAMPERED in e.get("name", "")), None
    )
    assert tampered_entry is not None, (
        f"Tampered artifact '{TAMPERED}' not found in audit report"
    )
    assert tampered_entry.get("overall", "").lower() == "fail", (
        f"Tampered artifact should have overall='fail', got '{tampered_entry.get('overall')}'"
    )


def test_audit_report_non_tampered_pass():
    """All non-tampered artifacts must be marked as 'pass' in the audit report."""
    with open("/app/audit_report.json", "r") as f:
        report = json.load(f)
    for entry in report["artifacts"]:
        name = entry.get("name", "")
        if TAMPERED in name:
            continue
        assert entry.get("overall", "").lower() == "pass", (
            f"Non-tampered artifact '{name}' should have overall='pass', "
            f"got '{entry.get('overall')}'"
        )


def test_audit_report_has_signature_details():
    """Each artifact entry must include signature check details."""
    with open("/app/audit_report.json", "r") as f:
        report = json.load(f)
    for entry in report["artifacts"]:
        name = entry.get("name", "")
        sigs = entry.get("signatures", [])
        assert isinstance(sigs, list), f"Artifact '{name}' must have 'signatures' list"
        assert len(sigs) > 0, f"Artifact '{name}' must have at least one signature entry"
        for sig in sigs:
            assert "signer" in sig, f"Signature entry missing 'signer' in {name}"
            assert "status" in sig, f"Signature entry missing 'status' in {name}"


def test_audit_report_has_attestation_details():
    """Each artifact entry must include attestation check details."""
    with open("/app/audit_report.json", "r") as f:
        report = json.load(f)
    for entry in report["artifacts"]:
        name = entry.get("name", "")
        atts = entry.get("attestations", [])
        assert isinstance(atts, list), f"Artifact '{name}' must have 'attestations' list"
        assert len(atts) > 0, f"Artifact '{name}' must have at least one attestation entry"
        for att in atts:
            assert "type" in att, f"Attestation entry missing 'type' in {name}"
            assert "status" in att, f"Attestation entry missing 'status' in {name}"


def test_verify_script_exists_and_executable():
    """verify.sh must exist and be executable."""
    assert os.path.exists("/app/verify.sh"), "/app/verify.sh not found"
    assert os.access("/app/verify.sh", os.X_OK), "/app/verify.sh is not executable"
