#!/usr/bin/env python3
"""
Creates in-toto v0.1 attestation statement JSON files for each required
attestation in the policy, using canonical build output hashes, then signs
each statement with cosign sign-blob.
"""

import hashlib
import json
import os
import subprocess
import sys

PREDICATE_TYPE_MAP = {
    "slsaprovenance": "https://slsa.dev/provenance/v0.2",
    "vuln": "https://cosign.sigstore.dev/attestation/vuln/v1",
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def build_provenance_predicate(artifact_name, digest):
    repo = artifact_name.replace(".bin", "")
    return {
        "builder": {"id": "https://ci.example.com/build"},
        "buildType": "https://example.com/pipeline/v1",
        "invocation": {
            "configSource": {
                "uri": f"https://github.com/example/{repo}",
                "digest": {"sha256": digest},
                "entryPoint": "Makefile",
            }
        },
        "buildConfig": {},
        "metadata": {
            "buildStartedOn": "2024-06-01T10:00:00Z",
            "buildFinishedOn": "2024-06-01T10:05:00Z",
            "completeness": {
                "parameters": True,
                "environment": True,
                "materials": True,
            },
            "reproducible": False,
        },
        "materials": [
            {
                "uri": f"https://github.com/example/{repo}",
                "digest": {"sha256": digest},
            }
        ],
    }


def build_vuln_predicate():
    return {
        "scanner": {
            "uri": "https://scanner.example.com/v1",
            "version": "2.1.0",
            "db": {
                "uri": "https://vulndb.example.com",
                "version": "2024-06-01",
            },
        },
        "scanStartedOn": "2024-06-01T12:00:00Z",
        "scanFinishedOn": "2024-06-01T12:02:00Z",
        "vulnerabilities": [],
        "metadata": {"scanStatus": "complete", "policyResult": "pass"},
    }


def main():
    os.environ["COSIGN_PASSWORD"] = ""

    with open("/app/policy.json") as f:
        policy = json.load(f)

    for art in policy["artifacts"]:
        name = art["name"]
        # Use canonical build output for digest computation
        build_output_path = f"/app/build_output/{name}"
        digest = sha256_file(build_output_path)

        for att in art["required_attestations"]:
            att_type = att["type"]
            signer = att["signer"]
            pred_uri = PREDICATE_TYPE_MAP.get(
                att_type, f"https://example.com/predicates/{att_type}"
            )

            # Build predicate
            if att_type == "slsaprovenance":
                predicate = build_provenance_predicate(name, digest)
            elif att_type == "vuln":
                predicate = build_vuln_predicate()
            else:
                predicate = {}

            # Construct in-toto v0.1 statement
            statement = {
                "_type": "https://in-toto.io/Statement/v0.1",
                "predicateType": pred_uri,
                "subject": [{"name": name, "digest": {"sha256": digest}}],
                "predicate": predicate,
            }

            statement_path = f"/app/attestations/{name}.{att_type}.statement"
            with open(statement_path, "w") as f:
                json.dump(statement, f, indent=2)

            # Sign the statement file with cosign sign-blob
            bundle_path = f"/app/attestations/{name}.{att_type}.bundle"
            result = subprocess.run(
                [
                    "cosign",
                    "sign-blob",
                    "--key",
                    f"/app/keys/{signer}.key",
                    "--bundle",
                    bundle_path,
                    "--tlog-upload=false",
                    "--yes",
                    statement_path,
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print(
                    f"ERROR signing attestation {name}.{att_type}: {result.stderr}",
                    file=sys.stderr,
                )
                sys.exit(1)

            print(f"Created attestation: {name}.{att_type} (signed by {signer})")


if __name__ == "__main__":
    main()
