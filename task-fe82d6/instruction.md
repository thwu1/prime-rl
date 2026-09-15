A multi-tenant encryption service backed by OpenBao's Transit secrets engine has failed a security compliance audit. The Transit engine is partially configured but contains multiple policy violations that must be remediated.

OpenBao is installed at `/usr/bin/bao`. Run `/app/init_state.sh` to start OpenBao in dev mode (root token: `test-root-token`, address: `127.0.0.1:8200`) and initialize the Transit engine to its current non-compliant state.

The organization's encryption key compliance policy is at `/app/compliance_policy.txt`. Plaintext data records are in `/app/data/`. An external AES-256 key for legacy system migration is at `/app/external_key.hex`.

Investigate the Transit engine's current key configuration, identify all policy violations, and bring the system into full compliance. Write your remediation as `/app/remediate.sh` — a script that assumes OpenBao is already running with the initial state loaded. OpenBao must remain running after the script completes. All evidence artifacts required by the policy must be produced under `/app/results/`.