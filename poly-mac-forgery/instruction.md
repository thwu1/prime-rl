A custom authenticated encryption protocol uses TEA for block encryption and a polynomial MAC over GF(2^64) for message authentication.

The environment contains:

- `/app/capture/traffic.pcap` — Network capture with mixed traffic (DNS, SNMP, etc.). Authenticated protocol messages use UDP port 4443 with payload format: `[version 1B][msg_id 2B big-endian][nonce 8B][ciphertext NB][tag 8B]` (current protocol version=0x02; older v1 packets on the same port are noise).
- `/app/bin/mac_engine` — Compiled ELF x86-64 binary implementing the MAC verification scheme. No source code is provided for the MAC implementation. The binary's `info` subcommand prints protocol metadata but not internal constants.
- `/app/db/sessions.db` — SQLite database with tables `sessions(session_id, nonce_hex, created_at, description)`, `messages(msg_id, session_id, ciphertext_len, status, captured_at)`, and `targets(target_id, session_id, ciphertext_hex, status, notes)`.
- `/app/crypto/tea.py` — TEA cipher reference implementation.
- `/app/data/target_info.txt` — Target identification.

Exploit a deployment weakness observable in the captured protocol traffic to forge a valid authentication tag for target_id=99. Write the forged tag as a 16-character lowercase hex string to `/app/output/forged_tag.txt`.