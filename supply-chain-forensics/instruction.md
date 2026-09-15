Four suspicious open-source packages have been flagged and placed in `/app/suspects/` for forensic analysis. Four known-clean packages with similar ecosystem coverage are provided in `/app/baselines/` for comparison. The baselines deliberately share surface-level similarities with the malicious ones (similar ecosystems, `postinstall` hooks, `init()` functions, `cmdclass` usage, hex constants).

Produce three deliverables:

**1. Forensic Report** (`/app/forensic_report.json`): For each suspicious package, reverse all obfuscation layers, classify the attack, and extract every IOC:

```json
{
  "packages": [
    {
      "name": "<package name>",
      "version": "<version from manifest>",
      "ecosystem": "<npm|go|pypi>",
      "attack_type": "<attack classification>",
      "obfuscation_technique": "<description of obfuscation method>",
      "execution_trigger": "<how malicious code gets executed>",
      "deobfuscated_strings": ["<all recovered plaintext strings>"],
      "iocs": {
        "domains": [], "ips": [], "urls": [],
        "file_paths": [], "credentials": [],
        "ports": [], "targeted_env_vars": []
      },
      "anti_forensics": ["<evasion techniques>"],
      "severity": "<critical|high|medium|low>"
    }
  ]
}
```

All IOC values must be exact — partial matches will not be accepted.

**2. YARA Detection Ruleset** (`/app/detection_rules.yar`): Design YARA rules that detect each malware family's unique signatures. Every suspicious package must trigger at least one rule when scanned with `yara -r /app/detection_rules.yar /app/suspects/`. No baseline package may trigger any rule when scanned against `/app/baselines/`.

**3. Threat Intelligence Assessment** (`/app/threat_assessment.json`): Evaluate the four attacks comparatively and design operational guidance. This assessment requires you to judge relative sophistication, attribute threat actors, map to the MITRE ATT&CK framework, evaluate your own YARA rules for resilience, and create a prioritized response plan:

```json
{
  "sophistication_ranking": [
    {
      "package": "<name>",
      "rank": 1,
      "score": 0.0,
      "justification": "<why this attack is ranked here — compare obfuscation complexity, anti-forensics, operational security, and evasion techniques relative to the other three>"
    }
  ],
  "mitre_attack_mapping": {
    "<package_name>": {
      "techniques": [
        {"id": "T1xxx.yyy", "name": "<technique name>", "evidence": "<specific evidence from this package>"}
      ]
    }
  },
  "attribution_analysis": {
    "num_clusters": 0,
    "clusters": [
      {
        "actor_id": "<identifier>",
        "packages": ["<package names in this cluster>"],
        "shared_ttps": ["<shared tactics/techniques/infrastructure>"],
        "confidence": "<high|medium|low>"
      }
    ],
    "rationale": "<explain why you grouped or separated these actors — what TTPs, infrastructure choices, or targeting patterns support your clustering>"
  },
  "rule_resilience_evaluation": [
    {
      "rule_name": "<YARA rule name>",
      "target_package": "<package it detects>",
      "brittle_indicators": ["<signatures an attacker could easily change without altering functionality>"],
      "robust_indicators": ["<signatures inherent to the attack's logic that cannot be trivially changed>"],
      "evasion_difficulty": "<low|medium|high>",
      "recommended_improvements": ["<how to make detection more resilient>"]
    }
  ],
  "remediation_priority": {
    "ordering": ["<package names from highest to lowest priority>"],
    "justification": "<explain the prioritization — consider blast radius, persistence, data impact, and stealth>"
  }
}
```

The sophistication ranking must reflect genuine comparative analysis: consider each attack's obfuscation depth, anti-forensics capabilities, operational security, and detection evasion. The MITRE ATT&CK mapping must use valid technique IDs (e.g., T1195.001) with specific evidence. The attribution analysis must justify clustering decisions based on observable TTPs, not speculation. The rule resilience evaluation must honestly assess which of your own YARA indicators are brittle vs. robust.