A corporate security team captured suspicious network activity originating from workstation WS-PC0117. The packet capture is at `/app/capture.pcap`. Analysts suspect a full compromise occurred but need an expert to reconstruct exactly what happened and build detection capability for the future.

## Part 1: Forensic Reconstruction

Analyze the capture and produce `/app/findings.json` with exactly these fields:

- `victim_ip` — IP address of the compromised workstation (string)
- `c2_server_ip` — IP address of the command-and-control server (string)
- `c2_port` — port used for C2 communications (integer)
- `encryption_key` — key string used to encrypt C2 payloads (string)
- `victim_hostname` — hostname as reported in C2 traffic (string)
- `victim_username` — username as reported in C2 traffic (string)
- `c2_commands` — ordered list of command names sent by the C2 server (list of strings)
- `compromised_credentials` — account-to-password mapping found in C2 traffic (dict)
- `exfiltrated_data` — complete plaintext of stolen data (string)
- `exfil_domain` — base domain used for data exfiltration (string)

## Part 2: Detection Engineering

Based on your forensic analysis, design Suricata-compatible IDS rules and write them to `/app/detection.rules`. Create at least three rules, each targeting a distinct phase of the attack you uncovered. Every rule must be a valid Suricata signature with `content` matches derived from specific protocol artifacts you discovered, along with `msg`, `sid`, and `rev` fields. The rules should detect the specific indicators from this intrusion, not generic network anomalies.