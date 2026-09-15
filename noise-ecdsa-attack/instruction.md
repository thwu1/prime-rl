A cloud storage service called VaultSync is implemented at `/app/vaultsync.py`. The service provides ECDSA-signed software update status checks and Noise protocol K-pattern handshake-based secure storage updates for registered users.

Audit the service's cryptographic implementation and exploit its flaws to:

1. Recover the server's ECDSA signing secret key
2. Forge a valid Noise K-pattern handshake message to overwrite a registered user's vault with attacker-controlled data

Create `/app/solution.py` implementing two functions:

- `recover_signing_key(params)` — returns the ECDSA secret key as an `int`
- `forge_vault_update(params, target_data)` — sends a forged handshake that sets the registered user's storage to `target_data` (bytes)

The `params` argument is an `AttackParams` instance (defined in `/app/vaultsync.py`) providing:

- `params.client_static_pk` — registered user's Noise static public key
- `params.server_static_pk` — server's Noise static public key
- `params.check_update()` — returns `(message_bytes, (r, s))` from the server's signed update check
- `params.update_storage(msg)` — sends a raw handshake message to the server's storage update endpoint

Run `python3 /app/verify.py` to validate your solution.