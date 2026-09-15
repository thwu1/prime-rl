#!/usr/bin/env python3
"""
Writes /app/verify.sh — a verification script that checks deployed artifacts
against signatures/attestations created from canonical build outputs, and
produces /app/audit_report.json.
"""

import os

VERIFY_SCRIPT = r'''#!/usr/bin/env python3
"""
Supply chain verification script.
Reads /app/policy.json, runs cosign verify-blob for each signature and
attestation requirement against DEPLOYED artifacts, checks attestation
digest integrity, and writes /app/audit_report.json.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

os.environ["COSIGN_PASSWORD"] = ""

POLICY_PATH = "/app/policy.json"
REPORT_PATH = "/app/audit_report.json"
KEYS_DIR = "/app/keys"
BUNDLES_DIR = "/app/bundles"
ATTESTATIONS_DIR = "/app/attestations"
ARTIFACTS_DIR = "/app/artifacts"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_signature(artifact, signer):
    """Verify a signature bundle against the deployed artifact."""
    bundle_path = os.path.join(BUNDLES_DIR, f"{artifact}.{signer}.bundle")
    pub_path = os.path.join(KEYS_DIR, f"{signer}.pub")
    artifact_path = os.path.join(ARTIFACTS_DIR, artifact)

    if not os.path.exists(bundle_path):
        return {"signer": signer, "status": "fail", "reason": "bundle not found"}
    if not os.path.exists(pub_path):
        return {"signer": signer, "status": "fail", "reason": "public key not found"}

    result = subprocess.run(
        [
            "cosign", "verify-blob",
            "--key", pub_path,
            "--bundle", bundle_path,
            "--insecure-ignore-tlog",
            artifact_path,
        ],
        capture_output=True,
        text=True,
    )
    entry = {"signer": signer, "status": "pass" if result.returncode == 0 else "fail"}
    if result.returncode != 0:
        entry["reason"] = result.stderr.strip()[:200]
    return entry


def verify_attestation(artifact, att_type, signer):
    """Verify an attestation: check statement signature AND digest match against deployed artifact."""
    statement_path = os.path.join(ATTESTATIONS_DIR, f"{artifact}.{att_type}.statement")
    bundle_path = os.path.join(ATTESTATIONS_DIR, f"{artifact}.{att_type}.bundle")
    pub_path = os.path.join(KEYS_DIR, f"{signer}.pub")
    artifact_path = os.path.join(ARTIFACTS_DIR, artifact)

    if not os.path.exists(statement_path) or not os.path.exists(bundle_path):
        return {"type": att_type, "status": "fail", "reason": "attestation files not found"}
    if not os.path.exists(pub_path):
        return {"type": att_type, "status": "fail", "reason": "public key not found"}

    # 1. Verify the attestation statement signature
    sig_result = subprocess.run(
        [
            "cosign", "verify-blob",
            "--key", pub_path,
            "--bundle", bundle_path,
            "--insecure-ignore-tlog",
            statement_path,
        ],
        capture_output=True,
        text=True,
    )
    if sig_result.returncode != 0:
        return {"type": att_type, "status": "fail", "reason": "attestation signature invalid"}

    # 2. Verify the deployed artifact digest matches the attestation subject
    try:
        with open(statement_path) as f:
            stmt = json.load(f)
        expected_digest = stmt["subject"][0]["digest"]["sha256"]
    except (json.JSONDecodeError, KeyError, IndexError):
        return {"type": att_type, "status": "fail", "reason": "malformed attestation statement"}

    actual_digest = sha256_file(artifact_path)
    if expected_digest != actual_digest:
        return {"type": att_type, "status": "fail", "reason": "artifact digest mismatch"}

    return {"type": att_type, "status": "pass"}


def main():
    with open(POLICY_PATH) as f:
        policy = json.load(f)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "artifacts": [],
        "summary": {"total": 0, "passed": 0, "failed": 0},
    }

    for art in policy["artifacts"]:
        name = art["name"]
        entry = {
            "name": name,
            "overall": "pass",
            "signatures": [],
            "attestations": [],
        }

        # Check all required signatures
        for signer in art["required_signers"]:
            sig_result = verify_signature(name, signer)
            entry["signatures"].append(sig_result)
            if sig_result["status"] == "fail":
                entry["overall"] = "fail"

        # Check all required attestations
        for att in art["required_attestations"]:
            att_result = verify_attestation(name, att["type"], att["signer"])
            entry["attestations"].append(att_result)
            if att_result["status"] == "fail":
                entry["overall"] = "fail"

        report["artifacts"].append(entry)
        report["summary"]["total"] += 1
        if entry["overall"] == "pass":
            report["summary"]["passed"] += 1
        else:
            report["summary"]["failed"] += 1

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))
    failed = report["summary"]["failed"]
    if failed > 0:
        print(f"\nWARNING: {failed} artifact(s) failed verification", file=sys.stderr)


if __name__ == "__main__":
    main()
'''


def main():
    with open("/app/verify.sh", "w") as f:
        f.write(VERIFY_SCRIPT)
    os.chmod("/app/verify.sh", 0o755)
    print("Wrote /app/verify.sh")


if __name__ == "__main__":
    main()
