#!/usr/bin/env python3
"""
Detection engineering: creates YARA rules from binary analysis,
validates them against artifacts, and produces a threat assessment
with MITRE ATT&CK mappings and defensive recommendations.
"""

import subprocess
import json
import os
import re
import struct
import hashlib

PACKED = "/app/artifacts/malware_packed.exe"
UNPACKED = "/app/artifacts/malware_unpacked.exe"
PCAP = "/app/evidence/infected.pcap"
REPORT = "/app/report.json"
RULES_FILE = "/app/detection/malware.yar"
VALIDATION_FILE = "/app/detection/validation.json"
ASSESSMENT_FILE = "/app/assessment.json"


def run(cmd, timeout=120):
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def find_public_ips_in_binary(path):
    """Find public IPv4 addresses in binary strings."""
    stdout, _, _ = run(f"strings -a {path}")
    ip_re = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')
    ips = set()
    for m in ip_re.finditer(stdout):
        ip = m.group(1)
        octets = [int(o) for o in ip.split(".")]
        if all(0 <= v <= 255 for v in octets):
            if octets[0] not in (0, 10, 127, 169, 255):
                if not (octets[0] == 192 and octets[1] == 168):
                    if not (octets[0] == 172 and 16 <= octets[1] <= 31):
                        ips.add(ip)
    return sorted(ips)


def hex_pattern(data, offset, length):
    """Extract hex byte string from binary data."""
    chunk = data[offset:offset + length]
    return " ".join(f"{b:02X}" for b in chunk)


def create_yara_rules():
    """Analyze binaries and create YARA detection rules."""
    os.makedirs("/app/detection", exist_ok=True)

    with open(PACKED, "rb") as f:
        packed_data = f.read()
    with open(UNPACKED, "rb") as f:
        unpacked_data = f.read()

    packed_md5 = md5_file(PACKED)
    unpacked_md5 = md5_file(UNPACKED)
    packed_size = len(packed_data)
    unpacked_size = len(unpacked_data)

    # --- Analyze packed binary for UPX markers ---
    upx_sig_offset = packed_data.find(b"UPX!")
    has_upx0 = b"UPX0" in packed_data
    has_upx1 = b"UPX1" in packed_data

    # Extract hex from around UPX signature area
    packed_hex_extra = ""
    if upx_sig_offset > 0 and upx_sig_offset + 12 <= len(packed_data):
        packed_hex_extra = hex_pattern(packed_data, upx_sig_offset, 8)

    # --- Analyze unpacked binary ---
    public_ips = find_public_ips_in_binary(UNPACKED)
    c2_ip = public_ips[0] if public_ips else ""

    # Extract PE header signature from unpacked binary
    unpacked_pe_hex = ""
    if len(unpacked_data) > 0x40:
        pe_off = struct.unpack_from("<I", unpacked_data, 0x3C)[0]
        if 0 < pe_off < len(unpacked_data) - 12:
            unpacked_pe_hex = hex_pattern(unpacked_data, pe_off, 8)

    # Find Windows API strings in unpacked binary for behavioral signatures
    stdout, _, _ = run(f"strings -a -n 8 {UNPACKED}")
    all_strings = [s.strip() for s in stdout.split("\n") if s.strip()]
    api_names = []
    for s in all_strings:
        if len(s) > 30 or len(s) < 8:
            continue
        if not re.match(r'^[A-Za-z]+$', s):
            continue
        if any(kw in s for kw in [
            "Socket", "Internet", "Http", "Connect",
            "Create", "Virtual", "Process", "Thread",
            "Write", "Alloc", "Protect", "Open"
        ]):
            api_names.append(s)

    # Deduplicate API names
    api_names = sorted(set(api_names))[:4]

    # --- Build YARA rule for packed variant ---
    packed_strings = [
        '$mz_header = { 4D 5A }',
        '$upx_magic = "UPX!"',
    ]
    packed_conditions = [
        '$mz_header at 0',
        '$upx_magic',
    ]

    if has_upx0:
        packed_strings.append('$upx_sect0 = "UPX0"')
    if has_upx1:
        packed_strings.append('$upx_sect1 = "UPX1"')
    if has_upx0 or has_upx1:
        parts = []
        if has_upx0:
            parts.append("$upx_sect0")
        if has_upx1:
            parts.append("$upx_sect1")
        packed_conditions.append(f'({" or ".join(parts)})')

    if packed_hex_extra:
        packed_strings.append(f'$upx_area = {{ {packed_hex_extra} }}')
        packed_conditions.append('$upx_area')

    packed_conditions.append(f'filesize > {max(packed_size - 4096, 1)}')
    packed_conditions.append(f'filesize < {packed_size + 4096}')

    # --- Build YARA rule for unpacked variant ---
    unpacked_strings = [
        '$mz_header = { 4D 5A }',
    ]
    unpacked_conditions = [
        '$mz_header at 0',
    ]

    if c2_ip:
        unpacked_strings.append(f'$c2_addr = "{c2_ip}"')
        unpacked_conditions.append('$c2_addr')

    for i, api in enumerate(api_names):
        unpacked_strings.append(f'$api_{i} = "{api}"')

    if api_names:
        api_refs = " or ".join(f"$api_{i}" for i in range(len(api_names)))
        unpacked_conditions.append(f'({api_refs})')

    if unpacked_pe_hex:
        unpacked_strings.append(f'$pe_sig = {{ {unpacked_pe_hex} }}')
        unpacked_conditions.append('$pe_sig')

    unpacked_conditions.append(f'filesize > {max(unpacked_size - 8192, 1)}')
    unpacked_conditions.append(f'filesize < {unpacked_size + 8192}')

    # --- Format and write YARA rules ---
    packed_str_block = "\n        ".join(packed_strings)
    packed_cond_block = " and\n            ".join(packed_conditions)
    unpacked_str_block = "\n        ".join(unpacked_strings)
    unpacked_cond_block = " and\n            ".join(unpacked_conditions)

    rules_text = f"""// YARA detection rules for drive-by download malware variants
// Generated from forensic binary analysis of extracted artifacts

rule Driveby_Malware_Packed_UPX {{
    meta:
        description = "Detects UPX-packed variant of drive-by download malware"
        author = "Forensic Analyst"
        date = "2024-01-15"
        sample_hash = "{packed_md5}"

    strings:
        {packed_str_block}

    condition:
        {packed_cond_block}
}}

rule Driveby_Malware_Unpacked {{
    meta:
        description = "Detects unpacked variant with hardcoded C2 infrastructure"
        author = "Forensic Analyst"
        date = "2024-01-15"
        sample_hash = "{unpacked_md5}"

    strings:
        {unpacked_str_block}

    condition:
        {unpacked_cond_block}
}}
"""

    with open(RULES_FILE, "w") as f:
        f.write(rules_text)

    print(f"[+] YARA rules written to {RULES_FILE}")
    print(f"    Packed rule: {len(packed_strings)} strings, {len(packed_conditions)} conditions")
    print(f"    Unpacked rule: {len(unpacked_strings)} strings, {len(unpacked_conditions)} conditions")

    return rules_text


def validate_rules():
    """Run YARA rules against artifacts and produce validation report."""
    results = {"scans": []}

    for target_name, target_path in [
        ("malware_packed.exe", PACKED),
        ("malware_unpacked.exe", UNPACKED),
    ]:
        stdout, stderr, rc = run(f"yara -s {RULES_FILE} {target_path}")

        rules_matched = []
        string_hits = 0

        if rc == 0 and stdout:
            for line in stdout.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("0x"):
                    string_hits += 1
                else:
                    parts = line.split()
                    if parts:
                        rules_matched.append(parts[0])

        scan_result = {
            "target": target_name,
            "target_path": target_path,
            "rules_matched": rules_matched,
            "total_string_hits": string_hits,
            "matched": len(rules_matched) > 0,
            "yara_exit_code": rc,
        }
        if rc != 0:
            scan_result["errors"] = stderr

        results["scans"].append(scan_result)

        status = "MATCH" if rules_matched else "NO MATCH"
        print(f"[{'+'if rules_matched else '!'}] {target_name}: {status} "
              f"({len(rules_matched)} rules, {string_hits} string hits)")

    with open(VALIDATION_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"[+] Validation results written to {VALIDATION_FILE}")
    return results


def create_assessment():
    """Create structured threat assessment with ATT&CK mappings."""

    # Load forensic report
    with open(REPORT) as f:
        report = json.load(f)

    # Determine victim IP from PCAP
    victim_ip = ""
    stdout, _, _ = run(
        f'tshark -r {PCAP} -Y "http.request" -T fields -e ip.src -c 1'
    )
    if stdout.strip():
        victim_ip = stdout.strip().split("\n")[0].strip()

    # Get HTTP request timeline
    stdout, _, _ = run(
        f'tshark -r {PCAP} -Y "http.request.method == GET" '
        f'-T fields -e frame.time_epoch -e ip.src -e ip.dst '
        f'-e http.host -e http.request.uri -E separator="|"'
    )
    http_requests = []
    for line in stdout.split("\n"):
        parts = line.strip().split("|")
        if len(parts) >= 5:
            http_requests.append({
                "time": parts[0], "src": parts[1], "dst": parts[2],
                "host": parts[3], "uri": parts[4],
            })

    jar_requests = [r for r in http_requests if r["uri"].endswith(".jar")]
    initial_req = http_requests[0] if http_requests else {}

    # C2 connection timing
    c2_ip = report.get("c2_ip", "")
    c2_dst = ""
    if c2_ip:
        stdout, _, _ = run(
            f'tshark -r {PCAP} -Y "ip.dst == {c2_ip} and tcp.flags.syn == 1" '
            f'-T fields -e ip.src -e ip.dst -c 1'
        )
        if stdout.strip():
            parts = stdout.strip().split("\t")
            if len(parts) >= 2:
                c2_dst = parts[1].strip()

    # --- Build attack stages ---
    attack_stages = []

    # Stage 1: Drive-by Compromise
    if initial_req:
        attack_stages.append({
            "stage_name": "Initial Access via Drive-by Compromise",
            "protocol": "HTTP",
            "src_ip": initial_req.get("src", victim_ip),
            "dst_ip": initial_req.get("dst", ""),
            "description": (
                f"Victim browsed to {report.get('initial_url', '')} "
                f"triggering the multi-stage exploit chain"
            ),
            "attck_technique_id": "T1189",
        })

    # Stage 2: Client-side exploitation
    if jar_requests:
        attack_stages.append({
            "stage_name": "Exploitation via Malicious Java Applets",
            "protocol": "HTTP",
            "src_ip": jar_requests[0].get("dst", ""),
            "dst_ip": jar_requests[0].get("src", victim_ip),
            "description": (
                f"Java exploit applets ({', '.join(report.get('java_applets', []))}) "
                f"delivered to exploit client-side Java runtime vulnerability"
            ),
            "attck_technique_id": "T1203",
        })

    # Stage 3: Malware download
    attack_stages.append({
        "stage_name": "Ingress Tool Transfer of Packed Executable",
        "protocol": "HTTP",
        "src_ip": initial_req.get("dst", "") if initial_req else "",
        "dst_ip": victim_ip,
        "description": (
            f"UPX-packed PE executable (MD5: {report.get('packed_malware_md5', '')}) "
            f"downloaded via HTTP following successful exploitation"
        ),
        "attck_technique_id": "T1105",
    })

    # Stage 4: Defense evasion
    attack_stages.append({
        "stage_name": "Defense Evasion via Executable Packing",
        "protocol": "N/A",
        "src_ip": "N/A",
        "dst_ip": "N/A",
        "description": (
            f"Malware packed with {report.get('packer_name', 'UPX')} to transform "
            f"binary signature and evade static antivirus detection"
        ),
        "attck_technique_id": "T1027",
    })

    # Stage 5: C2 communication
    attack_stages.append({
        "stage_name": "Command and Control via Direct IP",
        "protocol": "TCP",
        "src_ip": victim_ip,
        "dst_ip": c2_ip,
        "description": (
            f"Malware contacted hardcoded C2 server at {c2_ip} "
            f"without DNS resolution to avoid DNS-based detection mechanisms"
        ),
        "attck_technique_id": "T1071.001",
    })

    # Deduplicated technique list
    attck_techniques = sorted(set(s["attck_technique_id"] for s in attack_stages))

    # --- Detection gaps analysis ---
    detection_gaps = [
        {
            "stage_name": "Initial Access",
            "gap_description": (
                "Signature-based detection cannot identify novel drive-by URLs "
                "without prior threat intelligence; fast-flux domain registration "
                "outpaces URL reputation feed updates, and the initial request "
                "appears as ordinary HTTP GET traffic indistinguishable from "
                "legitimate browsing without content inspection"
            ),
        },
        {
            "stage_name": "Exploitation",
            "gap_description": (
                "Java applet exploit payloads can be obfuscated and polymorphic, "
                "defeating signature-based IDS rules targeting known CVEs; "
                "the applets are delivered as standard JAR files over HTTP which "
                "is indistinguishable from legitimate Java web application traffic "
                "without deep content inspection and behavioral analysis"
            ),
        },
        {
            "stage_name": "Malware Delivery",
            "gap_description": (
                "UPX packing transforms the executable's byte signature with each "
                "repack operation, rendering static file hash and byte-pattern "
                "signatures ineffective; the packed binary is transferred via "
                "standard HTTP which evades protocol-level anomaly detection"
            ),
        },
        {
            "stage_name": "Command and Control",
            "gap_description": (
                "Direct hardcoded IP connections bypass all DNS-based detection "
                "including DNS sinkholing, RPZ, and domain reputation systems; "
                "without corresponding DNS queries, passive DNS monitoring and "
                "domain-based threat intelligence are completely blind to this "
                "C2 channel"
            ),
        },
    ]

    # --- Prioritized defense recommendations ---
    defense_recommendations = [
        {
            "recommendation": (
                "Deploy a web proxy with TLS inspection and content disarm and "
                "reconstruct (CDR) capability to strip active content including "
                "Java applets, Flash, and suspicious JavaScript from web traffic"
            ),
            "addresses_stage": "Exploitation",
            "effectiveness_rationale": (
                "Highest priority because it neutralizes the exploit delivery "
                "mechanism regardless of specific CVE or payload variant, "
                "eliminating the entire class of browser-based exploitation "
                "that enables all subsequent attack stages; prevents the "
                "kill chain at its earliest actionable point"
            ),
        },
        {
            "recommendation": (
                "Implement network-level application control that blocks "
                "execution of PE files downloaded via HTTP/HTTPS from "
                "uncategorized or low-reputation domains"
            ),
            "addresses_stage": "Malware Delivery",
            "effectiveness_rationale": (
                "Second priority as it provides a defense-in-depth layer "
                "that catches malware delivery independent of packing or "
                "obfuscation; operates at the execution boundary rather "
                "than relying on signature detection, which is defeated "
                "by the UPX packing observed in this attack"
            ),
        },
        {
            "recommendation": (
                "Deploy behavioral network detection and response (NDR) with "
                "anomaly detection for TCP connections to external IPs that "
                "have no preceding DNS resolution from the same host"
            ),
            "addresses_stage": "Command and Control",
            "effectiveness_rationale": (
                "Third priority because the behavioral anomaly of TCP "
                "connections without DNS is a high-fidelity detection "
                "signal resistant to C2 infrastructure rotation; detects "
                "the specific evasion technique used (hardcoded IP) while "
                "remaining effective against variants that change the "
                "destination address"
            ),
        },
        {
            "recommendation": (
                "Integrate real-time threat intelligence feeds with DNS RPZ "
                "and web proxy URL categorization to block access to known "
                "malicious infrastructure at the network edge"
            ),
            "addresses_stage": "Initial Access",
            "effectiveness_rationale": (
                "Fourth priority as it provides preventive blocking of known "
                "malicious domains with low false-positive rates; however "
                "ranked lower because it relies on prior knowledge of threats "
                "and is ineffective against newly registered domains or "
                "direct-IP C2 channels as observed in this attack"
            ),
        },
        {
            "recommendation": (
                "Deploy browser isolation for user web sessions accessing "
                "uncategorized or recently registered domains to contain "
                "any exploit execution in a disposable sandbox"
            ),
            "addresses_stage": "Initial Access",
            "effectiveness_rationale": (
                "Fifth priority as a strategic defense-in-depth measure that "
                "isolates the browsing session from the endpoint regardless "
                "of the vulnerability exploited; addresses the root cause "
                "but requires significant infrastructure investment and "
                "may impact user experience for legitimate browsing"
            ),
        },
    ]

    assessment = {
        "attack_stages": attack_stages,
        "attck_techniques": attck_techniques,
        "detection_gaps": detection_gaps,
        "defense_recommendations": defense_recommendations,
    }

    with open(ASSESSMENT_FILE, "w") as f:
        json.dump(assessment, f, indent=2)

    print(f"[+] Threat assessment written to {ASSESSMENT_FILE}")
    print(f"    {len(attack_stages)} attack stages mapped")
    print(f"    ATT&CK techniques: {attck_techniques}")
    print(f"    {len(detection_gaps)} detection gaps analyzed")
    print(f"    {len(defense_recommendations)} defense recommendations prioritized")

    return assessment


def main():
    print("\n=== Phase 1: Creating YARA Detection Rules ===")
    create_yara_rules()

    print("\n=== Phase 2: Validating Rules Against Artifacts ===")
    validate_rules()

    print("\n=== Phase 3: Creating Threat Assessment ===")
    create_assessment()

    print("\n[*] Detection engineering pipeline complete.")


if __name__ == "__main__":
    main()
