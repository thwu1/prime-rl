A stripped ELF binary from a compromised Linux server is at `/app/malware_sample`. Incident notes are at `/app/incident_note.txt`. A known-benign binary is at `/app/benign_sample`.

The binary embeds two encrypted configuration blocks. One is the real operational C2 config; the other is a deliberate analyst trap containing plausible but fake IOCs. Plaintext decoy strings are also scattered throughout the binary to mislead basic analysis. A previous analyst reported IOCs from the wrong configuration — determine which is genuinely operational.

Write `/app/analysis_report.json` containing IOCs from the **real** config with these exact fields:
- `c2_primary`, `c2_secondary`, `campaign_id` (strings)
- `rc4_key_hex`, `xor_key_hex` (hex-encoded keys that protect the real config)
- `mutex` (string)
- `exfil_port` (integer)
- `persistence_path` (string)
- `real_config_id` — `"A"` or `"B"` (A = first block by .rodata offset, B = second)

Write `/app/detection.yar` — a YARA rule that matches `/app/malware_sample` but does NOT match `/app/benign_sample`.