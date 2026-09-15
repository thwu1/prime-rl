During a security incident investigation, network captures from a compromised server were recovered. `/opt/tls_forensics/captures/` contains 8 binary TLS records from two concurrent TLS 1.3 sessions that were interleaved on the wire. The records are unlabeled and unordered — they are not grouped by session.

Two client ephemeral private keys were also recovered:
- `/opt/tls_forensics/leaked_key_alpha.hex`
- `/opt/tls_forensics/leaked_key_beta.hex`

Intelligence indicates that one session's encrypted traffic was tampered with by an attacker who modified a single record in transit.

Perform a forensic evaluation: sort the records into their two sessions, determine which key belongs to which session, decrypt the intact session's application data, and identify the compromised session and its specific tampered record. Assess the security implications of the tampering.

Write:
- `/app/plaintext.txt` — the decrypted application-layer content from the intact session
- `/app/forensic_report.json` — a JSON object with these fields:
  - `intact_session`: session name whose data was successfully decrypted (`"alpha"` or `"beta"`)
  - `compromised_session`: session name whose data was tampered with
  - `tampered_record`: filename of the specific tampered record (e.g. `"record_03.bin"`)
  - `session_records`: object mapping each session name to a sorted list of its record filenames
  - `vulnerability_assessment`: string explaining the tampering and its security implications