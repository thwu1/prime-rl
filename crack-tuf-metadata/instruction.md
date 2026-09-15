A TUF (The Update Framework) repository at `/app/repository/` secures firmware updates using separate RSA signing keys assigned to different metadata roles. Public keys in DER format are also available at `/app/keystore/` for inspection with `openssl`. A payload file is at `/app/payload.bin`.

The RSA keys protecting this repository have exploitable cryptographic weaknesses. Analyze the key architecture, recover both private signing keys, and produce:

1. `/app/recovered_keys/targets_key.pem` — RSA private key (PEM) for the targets/snapshot signing role
2. `/app/recovered_keys/timestamp_key.pem` — RSA private key (PEM) for the timestamp signing role

Both must pass `openssl rsa -in <file> -check -noout`.

3. Forged repository at `/app/forged_repo/` injecting `payload.bin` as `firmware_v2.0.bin`:
   - `root.json` — unchanged from original
   - `targets.json` — new target added, version incremented, correctly signed per role
   - `snapshot.json` — updated to reference new targets version, correctly signed per role
   - `timestamp.json` — updated to reference new snapshot version, correctly signed per role
   - `targets/firmware_v2.0.bin` — the payload content

Each metadata file must be signed by the key assigned to its role in `root.json`. Existing targets must be preserved.