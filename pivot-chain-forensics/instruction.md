Your incident response team recovered forensic artifacts from a network breach affecting a segmented enterprise environment with four zones (DMZ, Corporate, Server Farm, Restricted). The attacker pivoted through multiple hosts via SSH tunneling to reach and exfiltrate data from the domain controller.

Post-breach review indicates the attacker employed anti-forensics techniques — planting fabricated log entries, shadow file modifications, and traffic records to construct a false attack narrative. Some artifacts contain both genuine evidence and disinformation.

Artifacts are in `/app/artifacts/`, organized by host subdirectory. Each may contain auth logs, process listings, shadow file fragments, network interface configs, netstat output, and/or bash history. Edge firewall logs, an internal traffic summary CSV, and partial network documentation (including firewall policy and host security baselines) are also provided. A wordlist is at `/app/wordlist.txt`. The `john` and `openssl` tools are pre-installed.

Analyze all artifacts to crack recoverable password hashes, distinguish genuine evidence from planted fabrications via cross-referencing for logical and temporal inconsistencies, classify each credential as real or planted, reconstruct the true multi-hop pivot path, and evaluate documented security policies against observed evidence to identify control violations that enabled the breach.

Write findings to `/app/report.json`:

```json
{
  "true_attack_path": [
    {
      "hop": 1,
      "source_host": "<hostname or EXTERNAL>",
      "source_ip": "<IP>",
      "destination_host": "<hostname>",
      "destination_ip": "<IP>",
      "username": "<SSH username>",
      "password": "<cracked plaintext password>",
      "tunnel_type": "<direct_ssh|ssh_dynamic_socks|ssh_local_forward|ssh_reverse_tunnel>"
    }
  ],
  "fabricated_evidence": [
    {
      "host": "<hostname>",
      "artifact": "<artifact filename>",
      "indicator": "<fabricated content>",
      "detection_reasoning": "<cross-reference inconsistency>"
    }
  ],
  "cracked_credentials": {
    "<username>": "<plaintext password>"
  },
  "genuine_attack_credentials": ["<username>"],
  "planted_credentials": ["<username>"],
  "dual_homed_hosts": {
    "<hostname>": ["<ip1>", "<ip2>"]
  },
  "exfiltrated_data": {
    "data_type": "<description>",
    "source_host": "<hostname>"
  },
  "policy_violations": [
    {
      "violated_policy": "<specific policy or baseline rule>",
      "evidence": "<artifact evidence>",
      "impact": "<how this enabled the breach>"
    }
  ]
}
```

The `tunnel_type` field must reflect the SSH flag used: `direct_ssh` for plain SSH, `ssh_dynamic_socks` for `-D`, `ssh_local_forward` for `-L`, or `ssh_reverse_tunnel` for `-R`.