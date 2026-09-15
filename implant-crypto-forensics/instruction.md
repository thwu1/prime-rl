A compromised server yielded artifacts from an APT implant used to exfiltrate classified documents. The implant's native cryptographic library implements two distinct cipher engines, and the recovered session metadata contains conflicting indicators about which engine was deployed for the exfiltration. The forensic acquisition process also corrupted portions of the stored authentication key material.

Your objectives:

1. Evaluate the security properties of both cipher engines and determine which was actually used for the exfiltration — and which is cryptographically weaker
2. Create a reusable detection tool that identifies the implant's exfiltration protocol in network captures, discriminating it from keepalive probes and other traffic sharing the same port
3. Recover corrupted authentication key material through cryptanalytic techniques
4. Decrypt the exfiltrated document

The exfiltrated document is a classified intelligence report in standard IC formatting (begins with a CLASSIFICATION header).

## Artifacts

- `/app/libcrypto.so` — Compiled native cryptographic library containing multiple cipher engine implementations
- `/app/agent_loader.py` — Partially recovered Python module that interfaced with the native library (incomplete heap dump reconstruction)
- `/app/implant.db` — SQLite database with operational configuration, stored key material, and session records (forensic acquisition flagged data integrity issues on some fields)
- `/app/exfil/` — Directory of encrypted data chunks
- `/app/exfil_traffic.pcap` — Network capture of the exfiltration session (contains mixed traffic including keepalive probes on the exfiltration port that share the same destination but use a different protocol magic)

## Deliverables

- `/app/analysis.json` — JSON object with your forensic evaluation:
  - `cipher_engine`: identifier of the cipher engine actually used (as named in the binary's exported symbols)
  - `recovered_auth_token`: the full corrected auth_token as a hex string
  - `corrupted_byte_positions`: JSON array of 0-indexed byte positions in the auth_token that were corrupted
  - `weaker_engine`: identifier of the cipher engine that is MORE vulnerable to known-plaintext attacks (requires evaluating both engines' cryptographic designs)
  - `kpa_bytes_for_full_key_recovery`: for the weaker engine, the minimum number of consecutive known-plaintext bytes (from position 0) needed to fully recover its encryption key
- `/app/exfil_detector.py` — A standalone Python3 detection tool that takes a pcap file path as `sys.argv[1]`, identifies packets using the implant's exfiltration protocol (not keepalive probes), and prints a JSON object to stdout with: `exfil_packet_count` (int), `sequence_numbers` (sorted list of ints), `total_payload_bytes` (int — payload data only, excluding the 8-byte protocol header per packet)
- `/app/decrypted_doc.txt` — The recovered plaintext document
- `/app/answer.txt` — The SHA-256 hex digest of the decrypted document contents