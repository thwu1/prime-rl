An enterprise OSPF network running FRR has suffered a complete cross-site connectivity outage caused by multiple independent faults. Two engineers have independently prepared remediation plans with proposed router configuration changes. Neither plan has been deployed yet; your job is to evaluate both, identify their flaws, and produce correct configurations.

The network state snapshot (captured during the outage) is at `/app/network_state/`:
- Router FRR configs: `/app/network_state/configs/*.conf`
- OSPF neighbor/interface state: `/app/network_state/state/`
- Connectivity test results: `/app/network_state/state/connectivity.txt`
- Network topology: `/app/topology.json`
- Configuration validator: `/app/validate.py`

Two proposed remediation plans:
- **Plan A**: `/app/proposals/plan_a/` (configs) + `/app/proposals/plan_a_notes.txt`
- **Plan B**: `/app/proposals/plan_b/` (configs) + `/app/proposals/plan_b_notes.txt`

Evaluate both proposals critically. For each, determine which original faults it correctly addresses, which it misses, and whether it introduces new problems — including regressions, security weaknesses, or violations of network engineering best practices (route filtering hygiene, principle of least privilege in OSPF network statements, defense-in-depth). The automated validator at `/app/validate.py` catches some but not all classes of issues; your evaluation must go beyond what it detects.

Produce:

1. Corrected router configs at `/app/fixed_configs/<router_name>.conf` that resolve all original faults without introducing regressions or weakening security posture.

2. `/app/evaluation.json` with this structure:
```json
{
  "plan_a": {
    "faults_correctly_fixed": ["..."],
    "faults_missed": ["..."],
    "regressions_introduced": ["..."],
    "recommendation": "reject|accept_with_changes|accept"
  },
  "plan_b": {
    "faults_correctly_fixed": ["..."],
    "faults_missed": ["..."],
    "regressions_introduced": ["..."],
    "recommendation": "reject|accept_with_changes|accept"
  },
  "final_approach": "<description of approach used for corrected configs>"
}
```

3. `/app/diagnosis.json`:
```json
{
  "faults": [
    {"device": "<router>", "root_cause": "<description>", "fix_applied": "<change>"}
  ]
}
```