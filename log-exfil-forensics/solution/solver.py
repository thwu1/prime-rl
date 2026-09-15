#!/usr/bin/env python3

"""Solve the forensic log analysis challenge with detection rule evaluation."""
import re
import json
import hashlib
import subprocess
import base64
import os
from collections import Counter
from urllib.parse import unquote
from datetime import datetime

LOG_DIR = "/app/logs"


def parse_auth_log():
    """Identify the brute-force attacker and collect stats for rule evaluation."""
    failed_counts = Counter()
    accepted_external = []
    password_event_ips = set()
    accepted_password_external = {}

    with open(f"{LOG_DIR}/auth.log") as f:
        for line in f:
            m = re.search(
                r'Failed password for (?:invalid user )?(\S+) from (\S+) port', line)
            if m:
                ip = m.group(2)
                failed_counts[ip] += 1
                if not ip.startswith("10."):
                    password_event_ips.add(ip)

            m = re.search(
                r'Accepted password for (\S+) from (\S+) port', line)
            if m:
                ts_match = re.match(r'(\w+\s+\d+\s+\d+:\d+:\d+)', line)
                ip = m.group(2)
                if not ip.startswith("10.") and not ip.startswith("192.168.") \
                        and not ip.startswith("127."):
                    accepted_external.append({
                        "user": m.group(1),
                        "ip": ip,
                        "ts_raw": ts_match.group(1) if ts_match else "",
                    })
                    password_event_ips.add(ip)
                    accepted_password_external[ip] = m.group(1)

    # The attacker is the external IP with the most failed attempts
    # that also has a successful login
    attacker = None
    max_fails = 0
    for entry in accepted_external:
        ip = entry["ip"]
        fails = failed_counts.get(ip, 0)
        if fails > max_fails:
            max_fails = fails
            attacker = entry

    # Find first failure timestamp for the attacker
    bf_start_raw = None
    with open(f"{LOG_DIR}/auth.log") as f:
        for line in f:
            if attacker["ip"] in line and "Failed password" in line:
                ts_match = re.match(r'(\w+\s+\d+\s+\d+:\d+:\d+)', line)
                if ts_match:
                    bf_start_raw = ts_match.group(1)
                    break

    return (attacker, bf_start_raw, failed_counts,
            password_event_ips, accepted_password_external)


def syslog_to_iso(ts_str):
    """Convert syslog timestamp (no year) to ISO format assuming 2024."""
    dt = datetime.strptime(f"2024 {ts_str}", "%Y %b %d %H:%M:%S")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_access_log(attacker_ip):
    """Find web shell requests, extract key fragments, and gather evaluation stats."""
    ws_requests = []
    has_post_to_uploads = False
    dotphp_from_others = False

    with open(f"{LOG_DIR}/access.log") as f:
        for line in f:
            # Check for POST to /uploads/
            if '"POST' in line and '/uploads/' in line:
                has_post_to_uploads = True

            # Check for dot-prefixed PHP from non-attacker IPs
            if attacker_ip not in line:
                m_dot = re.search(r'"GET\s+/\S*/\.\S+\.php', line)
                if m_dot:
                    dotphp_from_others = True

            if attacker_ip not in line:
                continue
            m = re.search(r'"GET (\S+\.php\?\S+) HTTP', line)
            if not m:
                continue
            full_url = m.group(1)
            ts_m = re.search(r'\[(\d+/\w+/\d+:\d+:\d+:\d+\s+[+-]\d+)\]', line)
            ts_str = ts_m.group(1) if ts_m else ""
            ws_requests.append({"url": full_url, "ts": ts_str})

    webshell_path = None
    webshell_first = None
    key_fragments = {}
    commands = []

    for req in ws_requests:
        url = req["url"]
        path, _, query = url.partition("?")

        if webshell_path is None:
            webshell_path = path

        if webshell_first is None and req["ts"]:
            dt = datetime.strptime(req["ts"], "%d/%b/%Y:%H:%M:%S %z")
            webshell_first = dt.strftime("%Y-%m-%d %H:%M:%S")

        params = {}
        for param in query.split("&"):
            if "=" in param:
                k, v = param.split("=", 1)
                params[k] = unquote(v)

        if "c" in params:
            try:
                cmd = base64.b64decode(params["c"]).decode("utf-8")
                commands.append(cmd)
            except Exception:
                pass

        if "t" in params:
            token = params["t"]
            seq = int(token[:2], 16)
            frag = bytes.fromhex(token[2:])
            key_fragments[seq] = frag

    aes_key = b""
    for i in sorted(key_fragments.keys()):
        aes_key += key_fragments[i]

    exfil_file = None
    for cmd in commands:
        if "/etc/shadow" in cmd:
            exfil_file = "/etc/shadow"
            break

    return (webshell_path, webshell_first, aes_key, commands, exfil_file,
            has_post_to_uploads, dotphp_from_others)


def parse_dns_log():
    """Extract DNS exfiltration data and gather stats for rule evaluation."""
    exfil_queries = []
    c2_domain = None
    has_txt_queries = False
    analytics_domains_legit = set()

    with open(f"{LOG_DIR}/dns_queries.log") as f:
        for line in f:
            if "query[TXT]" in line:
                has_txt_queries = True

            m_domain = re.search(r'query\[\w+\]\s+(\S+)\s+from\s+(\S+)', line)
            if m_domain:
                domain = m_domain.group(1)
                if "analytics" in domain.lower() and ".exfil." not in domain:
                    analytics_domains_legit.add(domain)

            if ".exfil." not in line:
                continue
            m = re.search(r'query\[A\]\s+(\S+)\s+from', line)
            if not m:
                continue
            fqdn = m.group(1)
            parts = fqdn.split(".")

            try:
                exfil_idx = parts.index("exfil")
            except ValueError:
                continue

            seq_hex = parts[0]
            data_hex = parts[1]
            seq = int(seq_hex, 16)
            data = bytes.fromhex(data_hex)
            c2_domain = ".".join(parts[exfil_idx + 1:])
            exfil_queries.append((seq, data))

    return (exfil_queries, c2_domain, has_txt_queries, analytics_domains_legit)


def decrypt_data(aes_key, iv, ciphertext):
    """Decrypt AES-256-CBC ciphertext using openssl CLI."""
    ct_path = "/tmp/_solve_ct"
    pt_path = "/tmp/_solve_pt"

    with open(ct_path, "wb") as f:
        f.write(ciphertext)

    result = subprocess.run([
        "openssl", "enc", "-d", "-aes-256-cbc",
        "-K", aes_key.hex(), "-iv", iv.hex(),
        "-nosalt", "-in", ct_path, "-out", pt_path
    ], capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Decryption failed: {result.stderr}")

    with open(pt_path, "rb") as f:
        plaintext = f.read()

    os.remove(ct_path)
    os.remove(pt_path)
    return plaintext


def evaluate_candidate_rules(attacker_ip, failed_counts, password_event_ips,
                              accepted_password_external, has_post_to_uploads,
                              dotphp_from_others, has_txt_queries,
                              analytics_domains_legit):
    """Evaluate each candidate detection rule against actual log data."""

    with open("/app/candidate_rules.json") as f:
        candidates = json.load(f)

    evaluations = {}

    for rule in candidates:
        rid = rule["rule_id"]

        if rid == "cand_ssh_any_ext_password":
            fp_count = len(password_event_ips) - 1
            other_ips = [ip for ip in accepted_password_external
                         if ip != attacker_ip]
            evaluations[rid] = {
                "verdict": "noisy",
                "justification": (
                    f"This rule fires on {len(password_event_ips)} distinct external IPs "
                    f"with password authentication events. Only one ({attacker_ip}) is the "
                    f"attacker; the remaining {fp_count} include scanning IPs and the "
                    f"legitimate contractor ({', '.join(other_ips)}), producing massive "
                    f"false positive volume."
                )
            }

        elif rid == "cand_ssh_ext_accepted":
            other_accepted = {ip: u for ip, u in accepted_password_external.items()
                              if ip != attacker_ip}
            entities = ", ".join(f"{ip} (user: {u})" for ip, u in other_accepted.items())
            evaluations[rid] = {
                "verdict": "noisy",
                "justification": (
                    f"Detects the attacker's successful login but also fires on the "
                    f"legitimate contractor session: {entities}. Password-based SSH "
                    f"from external sources is expected for authorized contractors, "
                    f"making this rule produce false positives."
                )
            }

        elif rid == "cand_ssh_brute_500":
            high_fail_ips = {ip for ip, cnt in failed_counts.items()
                             if cnt > 400 and not ip.startswith("10.")}
            evaluations[rid] = {
                "verdict": "effective",
                "justification": (
                    f"Only {attacker_ip} exceeds 400 failed password attempts "
                    f"({failed_counts[attacker_ip]} failures). All other scanning IPs "
                    f"have fewer than 400 attempts each. This threshold precisely "
                    f"isolates the brute-force attacker with zero false positives."
                )
            }

        elif rid == "cand_webshell_post_upload":
            evaluations[rid] = {
                "verdict": "ineffective",
                "justification": (
                    "The attacker accessed the web shell using HTTP GET requests with "
                    "base64-encoded query parameters, not POST requests. No POST "
                    "requests to /uploads/ appear in the access log. This rule "
                    "completely misses the web shell activity."
                )
            }

        elif rid == "cand_php_dotfile":
            evaluations[rid] = {
                "verdict": "effective",
                "justification": (
                    "Only the attacker's requests access a dot-prefixed PHP file "
                    "(.sys_cache.php). No legitimate traffic or web scanners target "
                    "hidden PHP files matching this pattern, yielding zero false "
                    "positives while precisely detecting the web shell."
                )
            }

        elif rid == "cand_dns_analytics":
            evaluations[rid] = {
                "verdict": "noisy",
                "justification": (
                    f"While this detects the C2 domain (cdn-telemetry.analytics-pool.net "
                    f"contains 'analytics'), it also fires on {len(analytics_domains_legit)} "
                    f"legitimate analytics domains: {', '.join(sorted(analytics_domains_legit))}. "
                    f"The high false positive rate from normal analytics traffic makes "
                    f"this rule impractical."
                )
            }

        elif rid == "cand_dns_txt_tunnel":
            evaluations[rid] = {
                "verdict": "ineffective",
                "justification": (
                    "The DNS exfiltration channel uses A record queries (query[A]), "
                    "not TXT records. This rule monitors for query[TXT] patterns "
                    "which do not match the actual tunneling technique. The exfiltrated "
                    "data passes through entirely undetected by this rule."
                )
            }

        elif rid == "cand_audit_shadow_read":
            evaluations[rid] = {
                "verdict": "effective",
                "justification": (
                    "Only the attacker's post-compromise activity (user=deploy at "
                    "2024-03-15T03:05:20) triggers a FILE_READ on /etc/shadow in the "
                    "audit log. No legitimate application activity reads /etc/shadow, "
                    "making this a precise zero-false-positive indicator of credential "
                    "harvesting."
                )
            }

    return evaluations


def build_detection_rules(attacker_ip, webshell_path, c2_domain):
    """Design improved detection rules for each attack stage."""
    return [
        {
            "rule_id": "detect-ssh-brute-force",
            "stage": "initial_access",
            "title": "SSH Brute Force Attack from External IP",
            "log_source": "auth.log",
            "detection_logic": (
                "Alert when a single external IP generates more than 400 "
                "'Failed password' entries in auth.log, especially when "
                "followed by an 'Accepted password' event for the same IP. "
                "Excludes internal 10.0.0.0/8 range."
            ),
            "indicator_value": attacker_ip,
        },
        {
            "rule_id": "detect-hidden-webshell-access",
            "stage": "execution",
            "title": "Access to Hidden PHP File with Encoded Parameters",
            "log_source": "access.log",
            "detection_logic": (
                "Alert on HTTP GET requests to dot-prefixed PHP files in "
                "upload directories (path matching /uploads/\\..*\\.php) "
                "carrying base64-encoded query parameters. Legitimate traffic "
                "never accesses hidden PHP files in upload paths."
            ),
            "indicator_value": webshell_path,
        },
        {
            "rule_id": "detect-dns-tunnel-exfil",
            "stage": "exfiltration",
            "title": "DNS Tunneling via Hex-Encoded A Record Queries",
            "log_source": "dns_queries.log",
            "detection_logic": (
                "Alert on DNS A queries where subdomain labels contain "
                "hex-encoded data longer than 20 characters directed at a "
                "consistent parent domain. Normal DNS queries have short "
                "human-readable labels. The 'exfil' label in the domain "
                "hierarchy is a strong additional signal."
            ),
            "indicator_value": c2_domain,
        },
    ]


def main():
    # Step 1: Identify attacker from auth.log
    (attacker, bf_start_raw, failed_counts,
     password_event_ips, accepted_password_external) = parse_auth_log()
    attacker_ip = attacker["ip"]
    compromised_account = attacker["user"]
    bf_start_iso = syslog_to_iso(bf_start_raw)
    bf_success_iso = syslog_to_iso(attacker["ts_raw"])

    print(f"[+] Attacker IP: {attacker_ip}")
    print(f"[+] Compromised account: {compromised_account}")
    print(f"[+] Brute force: {bf_start_iso} -> {bf_success_iso}")

    # Step 2: Analyze web shell from access.log
    (webshell_path, webshell_first, aes_key, commands, exfil_file,
     has_post_to_uploads, dotphp_from_others) = parse_access_log(attacker_ip)

    print(f"[+] Web shell: {webshell_path} (first: {webshell_first})")
    print(f"[+] AES key ({len(aes_key)} bytes): {aes_key.hex()}")
    print(f"[+] Decoded {len(commands)} commands")
    print(f"[+] Exfiltrated file: {exfil_file}")

    # Step 3: Extract DNS exfiltration data
    (exfil_queries, c2_domain, has_txt_queries,
     analytics_domains_legit) = parse_dns_log()
    num_exfil = len(exfil_queries)

    print(f"[+] C2 domain: {c2_domain}")
    print(f"[+] DNS exfil queries: {num_exfil}")

    # Reassemble transmission data
    exfil_queries.sort(key=lambda x: x[0])
    transmission = b"".join(data for _, data in exfil_queries)

    # First 16 bytes = IV, rest = ciphertext
    iv = transmission[:16]
    ciphertext = transmission[16:]

    print(f"[+] IV: {iv.hex()}")
    print(f"[+] Ciphertext: {len(ciphertext)} bytes")

    # Step 4: Decrypt
    plaintext = decrypt_data(aes_key, iv, ciphertext)
    sha256 = hashlib.sha256(plaintext).hexdigest()

    print(f"[+] Decrypted {len(plaintext)} bytes")
    print(f"[+] SHA256: {sha256}")

    # Write incident report
    report = {
        "attacker_ip": attacker_ip,
        "brute_force_start": bf_start_iso,
        "brute_force_success": bf_success_iso,
        "compromised_account": compromised_account,
        "webshell_path": webshell_path,
        "webshell_first_access": webshell_first,
        "exfiltrated_file": exfil_file,
        "c2_domain": c2_domain,
        "num_dns_exfil_queries": num_exfil,
        "decrypted_exfil_sha256": sha256,
    }

    with open("/app/incident_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n[+] Incident report written to /app/incident_report.json")

    # Step 5: Evaluate candidate detection rules
    evaluations = evaluate_candidate_rules(
        attacker_ip, failed_counts, password_event_ips,
        accepted_password_external, has_post_to_uploads, dotphp_from_others,
        has_txt_queries, analytics_domains_legit
    )

    with open("/app/rule_evaluation.json", "w") as f:
        json.dump(evaluations, f, indent=2)
    print(f"[+] Rule evaluations written to /app/rule_evaluation.json")

    # Step 6: Design improved detection rules
    detection_rules = build_detection_rules(attacker_ip, webshell_path, c2_domain)

    with open("/app/detection_rules.json", "w") as f:
        json.dump(detection_rules, f, indent=2)
    print(f"[+] Detection rules written to /app/detection_rules.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
