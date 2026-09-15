A network packet capture from a malware infection incident is available at:
`https://forensicscontest.com/contest05/infected.pcap` (MD5: `c09a3019ada7ab17a44537b069480312`)

The PCAP must be at `/app/evidence/infected.pcap`. All deliverables below must exist with the exact paths, keys, and formats specified.

## Forensic Artifacts (`/app/artifacts/`)

- `malware_packed.exe` — the malicious executable as it was delivered over the network
- `malware_unpacked.exe` — the same executable with its protection layer removed

## Forensic Report (`/app/report.json`)

JSON with exact keys:
- `victim_username` — Windows username of the compromised user
- `initial_url` — the full URL that initiated the infection chain
- `java_applets` — alphabetically sorted list of `.jar` exploit filenames delivered during the attack
- `packed_malware_md5` — MD5 hash (lowercase hex) of the delivered executable
- `packer_name` — the packing/protection tool applied to the executable
- `unpacked_malware_md5` — MD5 hash (lowercase hex) after removing the packing
- `c2_ip` — the IPv4 address of the command-and-control server contacted by the malware

## YARA Detection Rules (`/app/detection/malware.yar`)

Custom YARA rules that detect both the delivered and unpacked malware variants. Minimum two rules. Each rule must include a `meta:` section with `description`, `author`, and `date` fields. Rules must match when scanned against both `/app/artifacts/malware_packed.exe` and `/app/artifacts/malware_unpacked.exe`.

## YARA Validation Report (`/app/detection/validation.json`)

JSON documenting which YARA rules matched which artifact files and the number of pattern hits per match.

## Threat Assessment (`/app/assessment.json`)

A structured threat intelligence report with:
- `attack_stages` — ordered list of attack stages, each with `stage_name`, `protocol`, `src_ip`, `dst_ip`, `description`, and `attck_technique_id` (MITRE ATT&CK technique ID)
- `attck_techniques` — deduplicated list of all ATT&CK technique IDs observed across the attack chain
- `detection_gaps` — for each major attack stage, what signature-based network detection would miss and why; each entry needs `stage_name` and `gap_description`
- `defense_recommendations` — prioritized list (highest priority first) of actionable network-level defenses, each with `recommendation`, `addresses_stage`, and `effectiveness_rationale`