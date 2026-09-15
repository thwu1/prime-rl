#!/usr/bin/env python3
"""
Generate RSA key pairs and sign RPKI objects during Docker build.
Tampered objects (ROA13, ROA18, ASPA10, ASPA25) get signatures from
different data so verification fails. Private keys are deleted after use.
"""
import subprocess
import json
import os
import tempfile

APP = "/app"
TAMPERED = {"ROA13", "ROA18", "ASPA10", "ASPA25"}

entities = ["authority_alpha", "authority_beta", "authority_gamma", "authority_delta"]

# Generate RSA-2048 key pairs
os.makedirs(os.path.join(APP, "keys"), exist_ok=True)
os.makedirs(os.path.join(APP, "signatures"), exist_ok=True)

priv_keys = {}
for entity in entities:
    priv_path = "/tmp/{}_priv.pem".format(entity)
    pub_path = os.path.join(APP, "keys", "{}.pub".format(entity))
    subprocess.run(
        ["openssl", "genrsa", "-out", priv_path, "2048"],
        capture_output=True, check=True
    )
    subprocess.run(
        ["openssl", "rsa", "-in", priv_path, "-pubout", "-out", pub_path],
        capture_output=True, check=True
    )
    priv_keys[entity] = priv_path

# Load manifests
with open(os.path.join(APP, "roa_manifest.json")) as f:
    roa_manifest = json.load(f)
with open(os.path.join(APP, "aspa_manifest.json")) as f:
    aspa_manifest = json.load(f)

# Sign each RPKI object
for manifest in [roa_manifest, aspa_manifest]:
    for obj in manifest:
        obj_id = obj.get("roa_id") or obj.get("aspa_id")
        signer = obj["signing_entity"]
        data_file = os.path.join(APP, obj["data_file"])
        sig_file = os.path.join(APP, obj["signature_file"])
        priv_key = priv_keys[signer]

        if obj_id in TAMPERED:
            # Sign different data so signature verification will fail
            fd, tf_path = tempfile.mkstemp(suffix=".json")
            with os.fdopen(fd, "w") as tf:
                json.dump({"tampered": True, "id": obj_id}, tf)
            subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", priv_key,
                 "-out", sig_file, tf_path],
                capture_output=True, check=True
            )
            os.unlink(tf_path)
        else:
            subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", priv_key,
                 "-out", sig_file, data_file],
                capture_output=True, check=True
            )

# Clean up private keys
for path in priv_keys.values():
    os.unlink(path)

print("Crypto setup complete: {} keys, {} signatures".format(
    len(entities),
    sum(len(m) for m in [roa_manifest, aspa_manifest])
))
