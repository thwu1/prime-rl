A security audit of a key exchange system has recovered several artifacts, located in `/app/artifacts/`:

- `server_dhparams.pem` — The server's Diffie-Hellman parameter file (PEM-encoded)
- `audit.db` — SQLite database logging key exchanges and session metadata
- `session_capture.bin` — A captured encrypted session in a proprietary binary format

The audit team suspects the key exchange parameters may be weak, but has not been able to confirm this or recover any session content. Your objective is to recover the plaintext from the captured encrypted session.

Write the recovered plaintext to `/app/decrypted.txt` and the corresponding private key (as a decimal integer) to `/app/private_key.txt`.