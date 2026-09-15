A container supply chain security pipeline at `/app/pipeline/` must pass a compliance audit. The environment provides `cosign`, `crane`, `openssl`, and an OCI `registry` binary.

The pipeline directory contains artifacts from a previous failed attempt — certificates, signing keys, attestation stubs, and a status report — all with issues that must be diagnosed and corrected. No container images exist in the registry yet, and no offline verification copies have been prepared.

Investigate the existing artifacts, identify all defects, and produce a working pipeline that satisfies the following audit requirements:

**PKI** (`/app/pipeline/pki/`): A three-tier certificate hierarchy — root CA (`root-ca.pem`, `root-ca-key.pem`), intermediate CA (`intermediate-ca.pem`, `intermediate-ca-key.pem`), and leaf signing certificate (`leaf.pem`, `leaf-key.pem`). Root and intermediate must be CA certificates with certificate-signing key usage. The intermediate must constrain sub-CA depth to zero. The leaf must not be a CA and must permit only digital signature usage (no certificate signing). All certificates must use elliptic curve cryptography. `chain.pem` must contain the intermediate and root certificates. The full chain must pass `openssl verify`.

**Signing Keys** (`/app/pipeline/keys/`): `cosign.key` and `cosign.pub` — the public key must cryptographically match the leaf certificate's public key.

**Signed Images**: Two container images (`webapp:v1` and `worker:v1`) pushed to a local OCI registry and signed. Signatures must carry annotations `pipeline.version=v1` and `pipeline.stage=production`.

**Attestations** (`/app/pipeline/attestations/`): SLSA provenance predicate files `slsa-provenance-webapp.json` and `slsa-provenance-worker.json` — each must contain `builder` (with `id`), non-empty `materials` array, and `metadata` object. Vulnerability scan predicate `vuln-scan-webapp.json` for the webapp image. All attestations must be attached to their respective images and verifiable.

**Offline Verification** (`/app/pipeline/offline/webapp/` and `/app/pipeline/offline/worker/`): Images with all signatures and attestations saved for air-gapped verification. Signature verification and attestation verification must succeed using only the offline copies and the public key.

**Audit Report** (`/app/pipeline/audit-report.json`): JSON with an `images` array (each entry: `reference`, `digest` starting with `sha256:`, `signed`, `signature_verified`, `attestations`), a `pki` object (`root_ca_subject`, `intermediate_ca_subject`, `leaf_subject`, `chain_valid` set to `true`), and `overall_status` set to `"PASS"`.