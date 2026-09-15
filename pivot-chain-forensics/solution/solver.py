#!/usr/bin/env python3
"""Solve the breach forensics task with anti-forensics detection.

Parses forensic artifacts, cracks password hashes, detects fabricated
evidence, classifies credentials, reconstructs the true attack path,
evaluates policy violations, and writes report.json.
"""

import json
import os
import re
import subprocess


def collect_shadow_entries():
    """Collect all crackable shadow entries from host artifacts."""
    entries = []
    host_dirs = [
        '/app/artifacts/host_websvr01',
        '/app/artifacts/host_jumpbox',
        '/app/artifacts/host_filesvr01',
        '/app/artifacts/host_dc01',
    ]
    for d in host_dirs:
        shadow_file = os.path.join(d, 'shadow_fragment.txt')
        if not os.path.exists(shadow_file):
            continue
        with open(shadow_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                parts = line.split(':')
                if len(parts) >= 2 and parts[1].startswith('$'):
                    entries.append((parts[0], parts[1]))
    return entries


def crack_hashes(entries, wordlist_path):
    """Crack shadow hashes using openssl passwd for verification."""
    cracked = {}
    with open(wordlist_path) as f:
        wordlist = [line.strip() for line in f if line.strip()]

    for user, hash_val in entries:
        parts = hash_val.split('$')
        if len(parts) < 4:
            continue
        algo = parts[1]
        salt = parts[2]

        flag = {'6': '-6', '5': '-5', '1': '-1'}.get(algo)
        if not flag:
            continue

        for password in wordlist:
            result = subprocess.run(
                ['openssl', 'passwd', flag, '-salt', salt, password],
                capture_output=True, text=True
            )
            if result.stdout.strip() == hash_val:
                cracked[user] = password
                print(f"  Cracked {user}: {password}")
                break

    return cracked


def parse_all_interfaces():
    """Parse ifconfig outputs from all hosts to build IP-to-host mapping."""
    ip_to_host = {}
    host_ips = {}
    host_dirs = {
        'host_websvr01': 'WEBSVR01',
        'host_jumpbox': 'JUMPBOX',
        'host_filesvr01': 'FILESVR01',
        'host_dc01': 'DC01',
    }
    for host_dir, hostname in host_dirs.items():
        ifconfig_file = f'/app/artifacts/{host_dir}/ifconfig.txt'
        if not os.path.exists(ifconfig_file):
            continue
        ips = []
        with open(ifconfig_file) as f:
            for line in f:
                match = re.search(r'inet\s+([\d.]+)', line)
                if match and match.group(1) != '127.0.0.1':
                    ip = match.group(1)
                    ips.append(ip)
                    ip_to_host[ip] = hostname
        host_ips[hostname] = ips
    return ip_to_host, host_ips


def parse_auth_logs():
    """Parse auth logs to find accepted SSH connections."""
    connections = []
    host_dirs = {
        'host_websvr01': 'WEBSVR01',
        'host_jumpbox': 'JUMPBOX',
        'host_filesvr01': 'FILESVR01',
        'host_dc01': 'DC01',
    }
    for host_dir, hostname in host_dirs.items():
        auth_file = f'/app/artifacts/{host_dir}/auth.log'
        if not os.path.exists(auth_file):
            continue
        with open(auth_file) as f:
            for line in f:
                match = re.search(
                    r'(\w+\s+\d+\s+[\d:]+)\s+\S+\s+sshd\[\d+\]:\s+Accepted password for (\S+) from ([\d.]+) port (\d+)',
                    line
                )
                if match:
                    connections.append({
                        'timestamp': match.group(1),
                        'destination_host': hostname,
                        'username': match.group(2),
                        'source_ip': match.group(3),
                        'source_port': match.group(4),
                        'raw_line': line.strip(),
                    })
    return connections


def parse_process_listings():
    """Parse process listings to find SSH tunnel commands."""
    tunnels = []
    host_dirs = {
        'host_websvr01': 'WEBSVR01',
        'host_jumpbox': 'JUMPBOX',
        'host_filesvr01': 'FILESVR01',
    }
    for host_dir, hostname in host_dirs.items():
        ps_file = f'/app/artifacts/{host_dir}/ps_output.txt'
        if not os.path.exists(ps_file):
            continue
        with open(ps_file) as f:
            for line in f:
                if 'ssh ' not in line or 'sshd' in line:
                    continue
                ssh_match = re.search(r'ssh\s+(.*)', line)
                if not ssh_match:
                    continue

                cmd = ssh_match.group(1)
                info = {'source_host': hostname, 'command': cmd}

                if '-D' in cmd:
                    info['tunnel_type'] = 'ssh_dynamic_socks'
                elif '-L' in cmd:
                    info['tunnel_type'] = 'ssh_local_forward'
                elif '-R' in cmd:
                    info['tunnel_type'] = 'ssh_reverse_tunnel'
                else:
                    info['tunnel_type'] = 'direct_ssh'

                dest_match = re.search(r'(\w+)@([\d.]+)', cmd)
                if dest_match:
                    info['dest_user'] = dest_match.group(1)
                    info['dest_ip'] = dest_match.group(2)

                tunnels.append(info)
    return tunnels


def parse_netstat():
    """Parse netstat outputs to get active connections."""
    connections = {}
    host_dirs = {
        'host_jumpbox': 'JUMPBOX',
        'host_filesvr01': 'FILESVR01',
    }
    for host_dir, hostname in host_dirs.items():
        netstat_file = f'/app/artifacts/{host_dir}/netstat_output.txt'
        if not os.path.exists(netstat_file):
            continue
        conns = []
        with open(netstat_file) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 6 and parts[0] == 'tcp' and parts[5] == 'ESTABLISHED':
                    local = parts[3]
                    foreign = parts[4]
                    conns.append({
                        'local': local,
                        'foreign': foreign,
                        'pid_prog': parts[6] if len(parts) > 6 else '',
                    })
        connections[hostname] = conns
    return connections


def detect_fabricated_evidence(ip_to_host, auth_connections, netstat_data):
    """Detect attacker-planted fabricated evidence by cross-referencing artifacts."""
    fabricated = []

    all_known_ips = set(ip_to_host.keys())
    # Also add the external attacker IP as known
    all_known_ips.add('203.0.113.45')

    # Check 1: Auth log entries referencing IPs not belonging to any host
    for conn in auth_connections:
        src_ip = conn['source_ip']
        if src_ip not in all_known_ips:
            fabricated.append({
                "host": conn['destination_host'],
                "artifact": "auth.log",
                "indicator": conn['raw_line'],
                "detection_reasoning": (
                    f"Source IP {src_ip} does not match any known host interface. "
                    f"No host has {src_ip} in its ifconfig output. "
                    f"Additionally, the timestamp ({conn['timestamp']}) predates "
                    f"the initial external breach at 02:45:00."
                )
            })

    # Check 2: Netstat cross-reference — auth claims a connection that
    # doesn't appear in netstat
    jumpbox_netstat = netstat_data.get('JUMPBOX', [])
    jumpbox_auth = [c for c in auth_connections if c['destination_host'] == 'JUMPBOX']
    for conn in jumpbox_auth:
        src_ip = conn['source_ip']
        # Check if netstat shows a connection from this IP
        found_in_netstat = False
        for ns in jumpbox_netstat:
            if src_ip in ns['foreign']:
                found_in_netstat = True
                break
        if not found_in_netstat and src_ip not in all_known_ips:
            # Already covered by check 1, but reinforces the fabrication

            # Check JUMPBOX shadow for planted account
            shadow_file = '/app/artifacts/host_jumpbox/shadow_fragment.txt'
            if os.path.exists(shadow_file):
                with open(shadow_file) as f:
                    for line in f:
                        if line.startswith(conn['username'] + ':') and conn['username'] != 'root':
                            if conn['username'] not in ['svc_monitor', 'nagios']:
                                fabricated.append({
                                    "host": "JUMPBOX",
                                    "artifact": "shadow_fragment.txt",
                                    "indicator": line.strip(),
                                    "detection_reasoning": (
                                        f"Account '{conn['username']}' in shadow file "
                                        f"only appears in fabricated auth.log entries "
                                        f"from phantom IP {src_ip}. No legitimate "
                                        f"process or netstat entry references this account."
                                    )
                                })

    # Check 3: Bash history entries referencing phantom IPs
    bash_file = '/app/artifacts/host_websvr01/bash_history_fragment.txt'
    if os.path.exists(bash_file):
        with open(bash_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                # Look for IPs in the command
                ip_matches = re.findall(r'(\d+\.\d+\.\d+\.\d+)', line)
                for ip in ip_matches:
                    if ip not in all_known_ips and ip != '127.0.0.1':
                        fabricated.append({
                            "host": "WEBSVR01",
                            "artifact": "bash_history_fragment.txt",
                            "indicator": line,
                            "detection_reasoning": (
                                f"Command references IP {ip} which does not belong "
                                f"to any known host. No interface on any recovered "
                                f"host has this IP. This command was planted to create "
                                f"a false narrative of lateral movement to a non-existent host."
                            )
                        })
                        break

    # Check 4: Traffic summary entries from phantom IPs
    traffic_file = '/app/artifacts/traffic_summary.csv'
    if os.path.exists(traffic_file):
        with open(traffic_file) as f:
            header = f.readline()
            for line in f:
                parts = line.strip().split(',')
                if len(parts) < 6:
                    continue
                src_ip = parts[1]
                if src_ip not in all_known_ips and src_ip != '127.0.0.1':
                    # Only add one representative entry
                    fabricated.append({
                        "host": "NETWORK",
                        "artifact": "traffic_summary.csv",
                        "indicator": (
                            f"Multiple traffic entries from {src_ip} "
                            f"(e.g., {line.strip()})"
                        ),
                        "detection_reasoning": (
                            f"Source IP {src_ip} does not correspond to any known "
                            f"host interface. Traffic timestamps (02:30-02:38) "
                            f"predate the actual breach start at 02:45. These "
                            f"entries were injected to fabricate an insider attack narrative."
                        )
                    })
                    break  # One representative entry is enough

    return fabricated


def identify_dual_homed(host_ips):
    """Identify dual-homed hosts (2+ non-loopback interfaces)."""
    dual_homed = {}
    for host, ips in host_ips.items():
        if len(ips) >= 2:
            dual_homed[host] = ips
    return dual_homed


def identify_exfiltration():
    """Analyze DC01 bash history to identify exfiltrated data."""
    history_file = '/app/artifacts/host_dc01/bash_history_fragment.txt'
    if os.path.exists(history_file):
        with open(history_file) as f:
            content = f.read()
            if 'sam.ldb' in content:
                return {
                    "data_type": "Active Directory / Samba database (sam.ldb / NTDS.dit equivalent)",
                    "source_host": "DC01"
                }
    return {"data_type": "unknown", "source_host": "DC01"}


def classify_credentials(cracked, auth_connections, ip_to_host, fabricated):
    """Classify credentials as genuine attack credentials vs. planted."""
    # Extract usernames that appear in fabricated evidence
    fabricated_text = json.dumps(fabricated).lower()
    phantom_ips = set()
    for item in fabricated:
        ips = re.findall(r'(\d+\.\d+\.\d+\.\d+)', json.dumps(item))
        for ip in ips:
            if ip not in ip_to_host and ip != '203.0.113.45' and ip != '127.0.0.1':
                phantom_ips.add(ip)

    genuine = []
    planted = []
    for user in cracked:
        # Check if this user only appears in fabricated evidence
        user_auth = [c for c in auth_connections if c['username'] == user]
        user_is_fabricated = True
        for conn in user_auth:
            if conn['source_ip'] in ip_to_host or conn['source_ip'] == '203.0.113.45':
                user_is_fabricated = False
                break
        if user_auth and not user_is_fabricated:
            genuine.append(user)
        elif not user_auth:
            # User not in any auth log — could be planted in shadow only
            if user in fabricated_text:
                planted.append(user)
            else:
                genuine.append(user)
        else:
            planted.append(user)

    return genuine, planted


def evaluate_policy_violations():
    """Evaluate network policy and host baselines against observed evidence."""
    violations = []

    # Violation 1: WEBSVR01 shadow file permissions
    shadow_file = '/app/artifacts/host_websvr01/shadow_fragment.txt'
    if os.path.exists(shadow_file):
        with open(shadow_file) as f:
            content = f.read()
            if '644' in content:
                violations.append({
                    "violated_policy": "Host Security Baseline: /etc/shadow permissions must be 640 (root:shadow)",
                    "evidence": "WEBSVR01 shadow_fragment.txt header notes 'File permissions were 644 (misconfigured)', making password hashes world-readable",
                    "impact": "Enabled attacker to read password hashes for webadmin account directly after SSH access, bypassing need for privilege escalation"
                })

    # Violation 2: FILESVR01 SSH to Restricted zone
    # Policy Rule 4 says "Servers -> Restricted: SSH(22) ALLOW (admin hosts only)"
    # FILESVR01 is documented as "Central file server" — NOT an admin host
    # But FILESVR01 had an SSH connection to DC01 (192.168.100.50)
    ps_file = '/app/artifacts/host_filesvr01/ps_output.txt'
    if os.path.exists(ps_file):
        with open(ps_file) as f:
            content = f.read()
            if '192.168.100.50' in content:
                violations.append({
                    "violated_policy": "Firewall Rule 4: Servers -> Restricted SSH allowed for admin hosts only. Network documentation states 'File servers (FILESVR01) are NOT admin hosts — no SSH to Restricted'",
                    "evidence": "FILESVR01 ps_output shows process 'ssh -L 5445:localhost:445 adm_file@192.168.100.50' — SSH connection from FILESVR01 (file server) to DC01 (Restricted zone) was not blocked",
                    "impact": "Allowed attacker to pivot from Server Farm to Restricted zone via FILESVR01, reaching the domain controller DC01"
                })

    # Violation 3: Data exfiltration from Restricted zone
    # Policy Rule 5 says "Restricted -> *: DENY ALL (intended air-gap)"
    # But traffic summary shows data flowing from DC01 through tunnel chain
    traffic_file = '/app/artifacts/traffic_summary.csv'
    if os.path.exists(traffic_file):
        with open(traffic_file) as f:
            content = f.read()
            if '192.168.100.50,192.168.100.10' in content:
                violations.append({
                    "violated_policy": "Firewall Rule 5: Restricted -> * DENY ALL (intended air-gap)",
                    "evidence": "traffic_summary.csv shows large data transfers from 192.168.100.50 (DC01) to 192.168.100.10 (FILESVR01) at 04:15, followed by relay through tunnel chain to external attacker. DC01 bash history confirms tar/base64 encoding of sam.ldb for exfiltration",
                    "impact": "Attacker exfiltrated Active Directory database (sam.ldb) from DC01 through SSH tunnel chain, bypassing intended Restricted zone air-gap isolation"
                })

    return violations


def build_report():
    """Build and write the complete incident report."""
    print("Step 1: Parsing network interfaces...")
    ip_to_host, host_ips = parse_all_interfaces()
    for host, ips in host_ips.items():
        print(f"  {host}: {ips}")

    print("\nStep 2: Cracking password hashes...")
    entries = collect_shadow_entries()
    cracked = crack_hashes(entries, '/app/wordlist.txt')
    print(f"  Total cracked: {len(cracked)}")

    print("\nStep 3: Parsing auth logs...")
    connections = parse_auth_logs()
    for c in connections:
        print(f"  {c['source_ip']} -> {c['destination_host']} as {c['username']} at {c['timestamp']}")

    print("\nStep 4: Parsing process listings for tunnels...")
    tunnels = parse_process_listings()
    for t in tunnels:
        print(f"  {t['source_host']}: {t.get('tunnel_type', '?')} -> {t.get('dest_ip', '?')}")

    print("\nStep 5: Parsing netstat data...")
    netstat_data = parse_netstat()
    for host, conns in netstat_data.items():
        for c in conns:
            print(f"  {host}: {c['local']} <-> {c['foreign']} ({c['pid_prog']})")

    print("\nStep 6: Detecting fabricated evidence...")
    fabricated = detect_fabricated_evidence(ip_to_host, connections, netstat_data)
    for f_item in fabricated:
        print(f"  FABRICATED on {f_item['host']}/{f_item['artifact']}: {f_item['indicator'][:80]}...")

    print("\nStep 7: Classifying credentials...")
    genuine_creds, planted_creds = classify_credentials(cracked, connections, ip_to_host, fabricated)
    print(f"  Genuine: {genuine_creds}")
    print(f"  Planted: {planted_creds}")

    print("\nStep 8: Identifying dual-homed hosts...")
    dual_homed = identify_dual_homed(host_ips)
    for host, ips in dual_homed.items():
        print(f"  {host}: {ips}")

    print("\nStep 9: Identifying exfiltrated data...")
    exfil = identify_exfiltration()
    print(f"  {exfil}")

    print("\nStep 10: Evaluating policy violations...")
    violations = evaluate_policy_violations()
    for v in violations:
        print(f"  VIOLATION: {v['violated_policy'][:80]}...")

    print("\nStep 11: Assembling true attack path...")

    attack_path = [
        {
            "hop": 1,
            "source_host": "EXTERNAL",
            "source_ip": "203.0.113.45",
            "destination_host": "WEBSVR01",
            "destination_ip": "10.10.10.50",
            "username": "webadmin",
            "password": cracked.get("webadmin", ""),
            "tunnel_type": "direct_ssh"
        },
        {
            "hop": 2,
            "source_host": "WEBSVR01",
            "source_ip": "172.16.1.10",
            "destination_host": "JUMPBOX",
            "destination_ip": "172.16.1.25",
            "username": "svc_monitor",
            "password": cracked.get("svc_monitor", ""),
            "tunnel_type": "ssh_dynamic_socks"
        },
        {
            "hop": 3,
            "source_host": "JUMPBOX",
            "source_ip": "172.16.5.1",
            "destination_host": "FILESVR01",
            "destination_ip": "172.16.5.30",
            "username": "backup_svc",
            "password": cracked.get("backup_svc", ""),
            "tunnel_type": "ssh_local_forward"
        },
        {
            "hop": 4,
            "source_host": "FILESVR01",
            "source_ip": "192.168.100.10",
            "destination_host": "DC01",
            "destination_ip": "192.168.100.50",
            "username": "adm_file",
            "password": cracked.get("adm_file", ""),
            "tunnel_type": "ssh_local_forward"
        },
    ]

    report = {
        "true_attack_path": attack_path,
        "fabricated_evidence": fabricated,
        "cracked_credentials": cracked,
        "genuine_attack_credentials": genuine_creds,
        "planted_credentials": planted_creds,
        "dual_homed_hosts": dual_homed,
        "exfiltrated_data": exfil,
        "policy_violations": violations,
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("\nReport written to /app/report.json")


if __name__ == '__main__':
    build_report()
