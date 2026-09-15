#!/usr/bin/env python3
"""Generate structured audit report for the supply chain pipeline."""


import argparse
import json
import subprocess
import sys


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0


def cert_subject(path):
    r = subprocess.run(
        ["openssl", "x509", "-in", path, "-subject", "-noout"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return "UNKNOWN"
    return r.stdout.strip().replace("subject=", "").strip()


def verify_chain(pki_dir):
    return run([
        "openssl", "verify",
        "-CAfile", f"{pki_dir}/root-ca.pem",
        "-untrusted", f"{pki_dir}/intermediate-ca.pem",
        f"{pki_dir}/leaf.pem",
    ])


def verify_sig(keys_dir, offline_dir, name):
    return run([
        "cosign", "verify",
        "--key", f"{keys_dir}/cosign.pub",
        "--insecure-ignore-tlog",
        "--local-image", f"{offline_dir}/{name}",
    ])


def verify_att(keys_dir, offline_dir, name, att_type):
    return run([
        "cosign", "verify-attestation",
        "--key", f"{keys_dir}/cosign.pub",
        "--type", att_type,
        "--insecure-ignore-tlog",
        "--local-image", f"{offline_dir}/{name}",
    ])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pki-dir", required=True)
    parser.add_argument("--keys-dir", required=True)
    parser.add_argument("--offline-dir", required=True)
    parser.add_argument("--webapp-digest", required=True)
    parser.add_argument("--worker-digest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    chain_valid = verify_chain(args.pki_dir)

    webapp_sig = verify_sig(args.keys_dir, args.offline_dir, "webapp")
    webapp_slsa = verify_att(args.keys_dir, args.offline_dir, "webapp", "slsaprovenance")
    webapp_vuln = verify_att(args.keys_dir, args.offline_dir, "webapp", "vuln")

    worker_sig = verify_sig(args.keys_dir, args.offline_dir, "worker")
    worker_slsa = verify_att(args.keys_dir, args.offline_dir, "worker", "slsaprovenance")

    images = [
        {
            "reference": "localhost:5555/pipeline/webapp:v1",
            "name": "webapp",
            "digest": args.webapp_digest,
            "signed": True,
            "signature_verified": webapp_sig,
            "attestations": {
                "slsa_provenance": webapp_slsa,
                "vuln_scan": webapp_vuln,
            },
            "offline_verification": webapp_sig and webapp_slsa and webapp_vuln,
        },
        {
            "reference": "localhost:5555/pipeline/worker:v1",
            "name": "worker",
            "digest": args.worker_digest,
            "signed": True,
            "signature_verified": worker_sig,
            "attestations": {
                "slsa_provenance": worker_slsa,
            },
            "offline_verification": worker_sig and worker_slsa,
        },
    ]

    all_ok = all(img["signature_verified"] and img["offline_verification"] for img in images) and chain_valid

    report = {
        "images": images,
        "pki": {
            "root_ca_subject": cert_subject(f"{args.pki_dir}/root-ca.pem"),
            "intermediate_ca_subject": cert_subject(f"{args.pki_dir}/intermediate-ca.pem"),
            "leaf_subject": cert_subject(f"{args.pki_dir}/leaf.pem"),
            "chain_valid": chain_valid,
        },
        "overall_status": "PASS" if all_ok else "FAIL",
    }

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Audit report: {args.output}")
    print(f"Status: {report['overall_status']}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
