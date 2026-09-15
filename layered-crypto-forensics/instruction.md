Two samples of a suspected implant family were recovered from separate compromised Linux servers, along with forensic artifacts from the first incident:

- `/app/sample_alpha` — Stripped x86-64 ELF binary from the first compromised host
- `/app/sample_beta` — Stripped x86-64 ELF binary from a second, unrelated compromised host (different C2 infrastructure, same suspected actor)
- `/app/traffic_capture.pcap` — Network traffic from the first host during the compromise window
- `/app/process_memory.bin` — 64KB heap memory snapshot from sample_alpha's process
- `/app/incident_notes.txt` — Analyst's preliminary observations

Sample_alpha communicates over DNS with two distinct external domains. Each channel carries encrypted data. Which channel serves which purpose (data exfiltration vs. operational signaling), what encryption each uses, and which keys in memory correspond to which channel are all unknown.

Produce four deliverables:

1. `/app/recovered_data.txt` — The decrypted plaintext stolen through sample_alpha's data exfiltration channel.

2. `/app/analysis_report.json` — Forensic assessment of sample_alpha with fields:
   - `exfil_domain`: domain used for data exfiltration
   - `exfil_cipher`: name of the encryption algorithm protecting the exfiltration channel
   - `other_domain`: the other DNS domain
   - `other_cipher`: name of the encryption algorithm protecting the other channel
   - `exfil_cipher_param_hex`: a distinguishing implementation constant of the exfiltration cipher that differs from the standard algorithm specification (hex string, `"0x..."` format)

3. `/app/detection_assessment.json` — Comparative evaluation of both samples identifying which binary features are reliable family-level indicators versus operationally variable parameters. Must include:
   - `resilient_indicators`: array of objects with `feature` (string) and `reason` (string), identifying features stable across both samples that should anchor detection logic (minimum 3)
   - `brittle_indicators`: array of objects with `feature` (string) and `reason` (string), identifying features that vary between samples and must not be relied upon as sole detection criteria (minimum 2)

4. `/app/implant.yar` — A YARA detection rule for the implant **family**. It must match both `/app/sample_alpha` and `/app/sample_beta`, must not false-positive on `/usr/bin/ls`, and must define at least 3 indicator strings. Anchor detection on the resilient indicators — instance-specific strings that appear in only one sample will cause misses on the other.