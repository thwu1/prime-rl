A hardware security lab captured side-channel power traces from an embedded device performing cryptographic operations. The capture workspace is at `/app/`.

`/app/capture.db` is a SQLite database containing capture configuration, batch file metadata, and documentation of the binary trace format used by the raw data files under `/app/captures/`. Start by exploring this database to understand the data layout. `/app/oracle_info.txt` provides additional workspace documentation.

Your objective is to recover the device's full 128-bit secret key from the captured power traces. Write the 32-character lowercase hex key to `/app/recovered_key.hex`. Use `/app/verify <hex_key>` to check candidate keys.

After key recovery, decrypt `/app/encrypted_report.enc` — the encryption parameters can be found in the capture database. Write the plaintext to `/app/decrypted_report.txt`.