# Data Encryption Service — XAES-256-GCM

Encrypts confidential records using XAES-256-GCM (extended-nonce AES-256-GCM).

## Implementations

Three independent XAES-256-GCM implementations exist across the organization:

- **Alpha** (`/app/implementations/alpha/crypto.py`) — Python, deployed as `/app/service/crypto.py`
- **Beta** (`/app/implementations/beta/xaes_tool`) — Pre-compiled Go CLI binary
- **Gamma** (`/app/implementations/gamma/crypto.py`) — Python, independent implementation

## Beta CLI Usage

```
xaes_tool encrypt    <key_hex> <nonce_hex> <plaintext_hex> [aad_hex]
xaes_tool decrypt    <key_hex> <nonce_hex> <ciphertext_hex> [aad_hex]
xaes_tool derive-key <key_hex> <nonce_hex>
```

## Architecture

- `service/crypto.py` — Currently deployed XAES-256-GCM module (copy of Alpha)
- `service/keymanager.py` — Per-record key derivation from master key via HKDF-SHA256
- `service/process_batch.py` — Batch encryption of plaintext records
- `service/config.json` — Service configuration (master key, AAD prefix)

## Key Management

Each record is encrypted with a unique 256-bit key derived from the master key
using HKDF-SHA256 with the record ID as the info parameter. Each record also
gets a unique deterministic 192-bit nonce.

## Data Layout

- `data/plaintext/` — Source records (JSON)
- `data/encrypted/` — Encrypted output (JSON with hex-encoded ciphertext)
- `data/reports/` — Interoperability test reports

## Testing

Internal round-trip tests: `python3 -m pytest /app/tests/ -v`
