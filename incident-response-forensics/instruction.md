A Linux web server (Ubuntu 22.04, Flask + MySQL) was compromised. Forensic evidence is at `/app/evidence/` organized into subdirectories: `web/`, `system/`, `user_artifacts/`, `config/`, `network/`, `malware/`, and `filesystem/`.

Evidence includes server logs, configuration snapshots, shell histories, a network packet capture (`/app/evidence/network/capture.pcap`), and malware samples including a compiled ELF binary (`/app/evidence/malware/backdoor`) and an encoded dropper script.

Your job is to reconstruct the full attack chain and produce three deliverables.

## 1. Attack Chain Report — `/app/report/findings.json`

```json
{
  "attacker_source_ip": "<IP>",
  "c2_servers": [
    {"ip": "<IP>", "port": <int>, "protocol": "<tcp|https|dns>"}
  ],
  "initial_access": {
    "method": "<technique>",
    "vulnerable_endpoint": "<path>",
    "timestamp": "<ISO 8601>"
  },
  "privilege_escalation": {
    "method": "<technique>",
    "vulnerable_binary": "<path>"
  },
  "persistence_mechanisms": [
    {"type": "<category>", "detail": "<specifics>"}
  ],
  "backdoor_user": "<username>",
  "compromised_accounts": ["<user>"],
  "exfiltration": {
    "method": "<technique>",
    "target": "<what>",
    "destination": "<where>",
    "dns_domain": "<exfiltration domain>"
  },
  "malware_indicators": {
    "user_agent": "<beacon user-agent>",
    "xor_key_hex": "<hex of XOR key bytes>",
    "mutex": "<mutex name>",
    "beacon_interval_sec": <int>
  },
  "timeline": [
    {"timestamp": "<ISO 8601>", "event": "<description>"}
  ]
}
```

The report must be comprehensive. All C2 infrastructure must be identified — the attacker may have used more than one channel. All persistence mechanisms must be enumerated. All malware indicator fields must be populated with values derived from the evidence. The timeline must cover every significant phase of the attack.

## 2. Detection Rules — `/app/report/detection.yar`

Create YARA rules that detect the malware artifacts found under `/app/evidence/malware/`. Rules must match both the compiled binary and the decoded dropper script when scanned with the `yara` tool.

## 3. Remediation Assessment — `/app/report/remediation.json`

```json
{
  "findings": [
    {
      "id": "F-<N>",
      "title": "<title>",
      "severity": "critical|high|medium|low",
      "category": "<category>",
      "remediation_action": "<specific action>",
      "priority": "immediate|short_term|long_term",
      "justification": "<why this severity and priority>"
    }
  ]
}
```

Evaluate at least 8 distinct findings. Each persistence mechanism, the initial access vulnerability, the privilege escalation vector, missing egress filtering, and insufficient monitoring must be covered. Justify each severity and priority assignment based on the evidence.