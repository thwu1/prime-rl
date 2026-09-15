#!/usr/bin/env python3

"""
Solution for Vulnerability Assessment Pipeline Forensics and SSVC Triage.

Diagnoses and fixes five bugs across four pipeline components:
1. Database: CVE-2021-44228 and CVE-2021-45046 CVSS vectors are swapped
2. Config: 'confidentiality_reqirement' is misspelled (missing 'u')
3. Code: Environmental formula for Changed scope uses base formula
         (exponent 15, no 0.9731 scaling) instead of environmental formula
         (exponent 13, with 0.9731 scaling factor)
4. Database: CVE-2014-0160 CPE match has vulnerable=0 instead of 1
5. Traffic analyzer: tshark display filters use wrong fields/ports,
   causing Shellshock and Log4Shell exploit traffic to go undetected

Then evaluates each affected CVE against the SSVC decision framework
to produce triage decisions.
"""

import sqlite3
import json
import os
import subprocess

# ==============================================================
# Fix 1: Correct the swapped CVSS vectors in the database
# ==============================================================
# CVE-2021-44228 (Log4Shell) has AC:H but should have AC:L
# CVE-2021-45046 has AC:L but should have AC:H
# These were accidentally swapped during data import.

db = sqlite3.connect('/app/vulndb.sqlite')
db.execute(
    "UPDATE cves SET cvss_vector = 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H' "
    "WHERE cve_id = 'CVE-2021-44228'"
)
db.execute(
    "UPDATE cves SET cvss_vector = 'CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:C/C:H/I:H/A:H' "
    "WHERE cve_id = 'CVE-2021-45046'"
)
db.commit()
print("[+] Fix 1: Corrected swapped CVSS vectors for CVE-2021-44228 / CVE-2021-45046")

# ==============================================================
# Fix 4: Set vulnerable=1 for CVE-2014-0160 (Heartbleed) CPE match
# ==============================================================
# The CPE match entry for OpenSSL has vulnerable=0, causing Heartbleed
# to never match any inventory item.

db.execute("""
    UPDATE cpe_matches SET vulnerable = 1
    WHERE config_id IN (
        SELECT id FROM cpe_configurations WHERE cve_id = 'CVE-2014-0160'
    )
""")
db.commit()
db.close()
print("[+] Fix 4: Set vulnerable=1 for CVE-2014-0160 OpenSSL CPE match")

# ==============================================================
# Fix 2: Correct the misspelled config key
# ==============================================================
# env_config.json has "confidentiality_reqirement" (missing 'u')
# This causes the code to fall back to NOT_DEFINED (1.0) instead of HIGH (1.5)

with open('/app/env_config.json') as f:
    config = json.load(f)

if 'confidentiality_reqirement' in config and 'confidentiality_requirement' not in config:
    config['confidentiality_requirement'] = config.pop('confidentiality_reqirement')
    with open('/app/env_config.json', 'w') as f:
        json.dump(config, f, indent=2)
    print("[+] Fix 2: Corrected 'confidentiality_reqirement' -> 'confidentiality_requirement'")

# ==============================================================
# Fix 3: Correct the environmental formula for Changed scope
# ==============================================================
# The code uses the base impact formula for Changed scope environmental:
#   7.52 * (miss - 0.029) - 3.25 * ((miss - 0.02) ** 15)
# The correct CVSS v3.1 environmental formula for Changed scope is:
#   7.52 * (miss - 0.029) - 3.25 * ((miss * 0.9731 - 0.02) ** 13)
#
# Key differences: 0.9731 scaling factor on MISS, exponent 13 instead of 15

with open('/app/vuln_assess.py') as f:
    code = f.read()

old_formula = "7.52 * (miss - 0.029) - 3.25 * ((miss - 0.02) ** 15)"
new_formula = "7.52 * (miss - 0.029) - 3.25 * ((miss * 0.9731 - 0.02) ** 13)"

# The formula appears twice: once in compute_base_score (ISS-based, correct for base)
# and once in compute_environmental_score (MISS-based, needs fix).
# We need to fix only the one in compute_environmental_score.
lines = code.split('\n')
fixed_lines = []
in_environmental = False
for line in lines:
    if 'def compute_environmental_score' in line:
        in_environmental = True
    elif line.startswith('def ') and in_environmental:
        in_environmental = False
    if in_environmental and old_formula in line:
        line = line.replace(old_formula, new_formula)
    fixed_lines.append(line)

code = '\n'.join(fixed_lines)

with open('/app/vuln_assess.py', 'w') as f:
    f.write(code)
print("[+] Fix 3: Corrected environmental Changed-scope formula (0.9731 scaling, exponent 13)")

# ==============================================================
# Fix 5: Correct tshark display filters in traffic analyzer
# ==============================================================
# Bug A: Shellshock detection uses http.request.uri but the exploit
#   pattern "() {" is in the User-Agent header, not the URI.
#   Fix: change to http.user_agent
#
# Bug B: Log4Shell detection filters on tcp.dstport==80 and searches
#   http.user_agent, but the JNDI payload is in the X-Api-Token header
#   sent to port 8080. tshark doesn't auto-dissect port 8080 as HTTP,
#   and X-Api-Token is a non-standard header without a dedicated field.
#   Fix: use 'frame contains "jndi:"' to search raw frame bytes.

with open('/app/traffic_analyzer.sh') as f:
    script = f.read()

# Fix Shellshock filter: search User-Agent, not URI
script = script.replace(
    'http.request.uri contains "() {"',
    'http.user_agent contains "() {"'
)

# Fix Log4Shell filter: search all frame data for JNDI patterns
script = script.replace(
    'tcp.dstport == 80 and http.user_agent contains "jndi:"',
    'frame contains "jndi:"'
)

with open('/app/traffic_analyzer.sh', 'w') as f:
    f.write(script)
print("[+] Fix 5: Corrected tshark display filters for Shellshock and Log4Shell detection")

# ==============================================================
# Re-run the fixed pipeline
# ==============================================================
print("\n[*] Running fixed traffic analyzer...")
subprocess.run(["bash", "/app/traffic_analyzer.sh"], cwd="/app")

print("\n[*] Running fixed assessment pipeline...")
subprocess.run(["python3", "/app/vuln_assess.py"], cwd="/app")

print("\n[+] All fixes applied and pipeline re-run successfully")

# ==============================================================
# SSVC Triage Evaluation
# ==============================================================
# Evaluate each affected vulnerability using the SSVC framework
# with corrected pipeline output.

print("\n[*] Performing SSVC triage evaluation...")

# Load corrected pipeline output
with open('/app/affected_inventory.json') as f:
    affected = json.load(f)

with open('/app/active_threats.json') as f:
    threats = json.load(f)
    active_cves = {e['cve_id'] for e in threats.get('active_exploits', [])}

with open('/app/mission_impact.json') as f:
    mission_data = json.load(f)

with open('/app/ssvc_policy.json') as f:
    ssvc_policy = json.load(f)

# Read corrected CVSS vectors from database
db = sqlite3.connect('/app/vulndb.sqlite')
vectors = {}
for cve_id, vector in db.execute('SELECT cve_id, cvss_vector FROM cves'):
    vectors[cve_id] = vector
db.close()


def parse_cvss_metrics(vector_string):
    """Parse CVSS v3.1 vector string into metric abbreviation dict."""
    prefix = "CVSS:3.1/"
    if vector_string.startswith(prefix):
        vector_string = vector_string[len(prefix):]
    metrics = {}
    for part in vector_string.split("/"):
        key, value = part.split(":")
        metrics[key] = value
    return metrics


# Determine SSVC decision points for each affected CVE
ssvc_decisions = []
mission_rank = {"high": 2, "medium": 1, "low": 0}

for cve_id in affected:
    vector = vectors[cve_id]
    m = parse_cvss_metrics(vector)

    # Exploitation: active if observed in traffic analysis
    exploitation = "active" if cve_id in active_cves else "none"

    # Automatable: AV:N AND AC:L AND UI:N (per SSVC policy)
    automatable = "yes" if (m["AV"] == "N" and m["AC"] == "L" and m["UI"] == "N") else "no"

    # Technical Impact: total if all three CIA are HIGH
    technical_impact = "total" if (m["C"] == "H" and m["I"] == "H" and m["A"] == "H") else "partial"

    # Mission prevalence: highest among affected inventory items
    affected_items = affected[cve_id]
    max_mission = "low"
    for item_id in affected_items:
        if item_id in mission_data:
            mp = mission_data[item_id]["mission_prevalence"]
            if mission_rank.get(mp, 0) > mission_rank.get(max_mission, 0):
                max_mission = mp

    # Traverse the SSVC decision tree (first matching rule wins)
    decision = None
    for rule in ssvc_policy["decision_tree"]["rules"]:
        if rule["exploitation"] != exploitation:
            continue
        if rule["automatable"] != automatable:
            continue
        if "technical_impact" in rule and rule["technical_impact"] != technical_impact:
            continue
        if "mission_prevalence" in rule:
            mp_rule = rule["mission_prevalence"]
            if isinstance(mp_rule, list):
                if max_mission not in mp_rule:
                    continue
            elif mp_rule != max_mission:
                continue
        decision = rule["decision"]
        break

    ssvc_decisions.append({
        "cve_id": cve_id,
        "exploitation": exploitation,
        "automatable": automatable,
        "technical_impact": technical_impact,
        "mission_prevalence": max_mission,
        "decision": decision
    })

# Sort by decision priority (Act, Attend, Track*, Track), then CVE ID ascending
priority_order = {"Act": 0, "Attend": 1, "Track*": 2, "Track": 3}
ssvc_decisions.sort(key=lambda x: (priority_order[x["decision"]], x["cve_id"]))

with open('/app/ssvc_decisions.json', 'w') as f:
    json.dump(ssvc_decisions, f, indent=2)
print(f"[+] SSVC triage: {len(ssvc_decisions)} decisions produced")

# Print summary
for entry in ssvc_decisions:
    print(f"    {entry['cve_id']}: {entry['decision']} "
          f"(expl={entry['exploitation']}, auto={entry['automatable']}, "
          f"impact={entry['technical_impact']}, mission={entry['mission_prevalence']})")

print("\n[+] All tasks complete")
