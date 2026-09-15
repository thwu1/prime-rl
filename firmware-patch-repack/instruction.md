A firmware image at `/app/firmware.bin` uses a proprietary multi-section binary container with per-section SHA-256 hashes and HMAC authentication. Sections may be raw, compressed, or encrypted. Reverse-engineer the container format, remediate all security issues described below, and write a valid firmware to `/app/firmware_patched.bin`.

## Gateway Binary Hardening

The gateway ELF binary inside the compressed filesystem payload contains an embedded security configuration data block identifiable by a distinctive ASCII marker. Multiple fields have insecure defaults:

- Channel validation bounds limit has an off-by-one error that permits one channel index beyond the valid range — the exclusive upper bound must equal the actual number of channels (16)
- Authentication enforcement is disabled — must be enabled
- TLS transport mode is off — must be set to required (strictest level, numeric value 2)
- A debug interface backdoor is active — must be disabled
- Certificate verification is off — must be enabled
- Minimum cryptographic key size is dangerously low — must be at least 2048 bits

After patching, `gateway --validate 15` must succeed and `gateway --validate 16` must be rejected. The `gateway --security` subcommand displays current security configuration values.

## Encrypted Configuration

The gateway configuration is stored as a separately encrypted section in the firmware container, not inside the filesystem payload. The encryption key is available as a hex-encoded field within the firmware's metadata section. Decrypt the configuration, set `tls_enabled` to `true`, change the cipher suite from `RC4-MD5` to `AES256-GCM`, and re-encrypt with the original key and scheme.

## Additional Requirements

- In the SquashFS modules image within the filesystem payload, set `REMOTE_DEBUG_ENABLED` to `False` in the diagnostics script.
- Update the firmware version to `2.0.0` in both the metadata section and the filesystem's version file.
- Create `var/manifest.json` in the filesystem containing `"version"` (`"2.0.0"`), `"gateway_sha256"` (hex SHA-256 of the patched gateway binary), and `"config_sha256"` (hex SHA-256 of the modified plaintext configuration).
- All per-section hashes and the container HMAC must be recomputed to reflect modifications.