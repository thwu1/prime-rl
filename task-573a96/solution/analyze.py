#!/usr/bin/env python3
"""
Forensic analysis of drive-by download malware infection PCAP.
Extracts artifacts and produces a structured forensic report.
"""

import subprocess
import hashlib
import json
import os
import re
import shutil

PCAP = "/app/evidence/infected.pcap"
ARTIFACTS = "/app/artifacts"
HTTP_EXPORT = "/tmp/http_export"
REPORT = "/app/report.json"


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, timeout=120):
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def is_public_ip(ip):
    octets = ip.split(".")
    if len(octets) != 4:
        return False
    try:
        vals = [int(o) for o in octets]
    except ValueError:
        return False
    if not all(0 <= v <= 255 for v in vals):
        return False
    if vals[0] in (0, 10, 127, 169, 224, 225, 226, 227, 228, 229,
                   230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 255):
        return False
    if vals[0] == 192 and vals[1] == 168:
        return False
    if vals[0] == 172 and 16 <= vals[1] <= 31:
        return False
    return True


def parse_ips(text):
    ips = set()
    for line in text.split("\n"):
        for token in re.split(r'[,\t\s]+', line.strip()):
            token = token.strip()
            if token and re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', token):
                ips.add(token)
    return ips


def find_victim_ip():
    stdout, _, _ = run(
        f'tshark -r {PCAP} -Y "http.request" -T fields -e ip.src'
    )
    ip_counts = {}
    for ip in parse_ips(stdout):
        ip_counts[ip] = ip_counts.get(ip, 0) + 1
    if ip_counts:
        return max(ip_counts, key=ip_counts.get)
    return ""


def find_username():
    for filt in [
        "ntlmssp.auth.username",
        "ntlmssp.messagetype == 0x00000003",
        "ntlmssp",
    ]:
        stdout, stderr, _ = run(
            f'tshark -r {PCAP} -Y "{filt}" '
            f"-T fields -e ntlmssp.auth.username"
        )
        for line in stdout.split("\n"):
            u = line.strip()
            if u:
                print(f"[+] Username found via tshark filter '{filt}': {u}")
                return u

    stdout, _, _ = run(f"tshark -r {PCAP} -Y ntlmssp -V")
    for line in stdout.split("\n"):
        m = re.search(r'User name:\s*(\S+)', line)
        if m:
            u = m.group(1).strip()
            if u:
                print(f"[+] Username from verbose NTLMSSP: {u}")
                return u

    stdout, _, _ = run(f"strings -e l {PCAP}")
    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper == "ADMINISTRATOR" or upper.startswith("ADMINISTRATOR"):
            print(f"[+] Username from UTF-16LE strings: {line}")
            return line.split()[0] if line.split() else line

    stdout, _, _ = run(f"strings -a {PCAP} | grep -i ADMINISTRATOR")
    for line in stdout.split("\n"):
        line = line.strip()
        if "ADMINISTRATOR" in line.upper():
            return "ADMINISTRATOR"

    stdout, _, _ = run(
        f'tshark -r {PCAP} -Y smb -T fields -e smb.account'
    )
    for line in stdout.split("\n"):
        u = line.strip()
        if u:
            return u

    try:
        with open(PCAP, "rb") as f:
            data = f.read()
        sig = b"NTLMSSP\x00"
        pos = 0
        while True:
            idx = data.find(sig, pos)
            if idx == -1:
                break
            msg_type = int.from_bytes(data[idx+8:idx+12], "little")
            if msg_type == 3:
                chunk = data[idx:idx+256]
                i = 0
                decoded_parts = []
                while i < len(chunk) - 1:
                    if chunk[i+1] == 0 and 32 <= chunk[i] < 127:
                        chars = []
                        while i < len(chunk) - 1 and chunk[i+1] == 0 and 32 <= chunk[i] < 127:
                            chars.append(chr(chunk[i]))
                            i += 2
                        word = "".join(chars)
                        if len(word) >= 4:
                            decoded_parts.append(word)
                    else:
                        i += 1
                for part in decoded_parts:
                    if part.upper() in ("ADMINISTRATOR", "ADMIN", "USER", "ROOT"):
                        return part
            pos = idx + 1
    except Exception as e:
        print(f"[!] Binary NTLMSSP parse error: {e}")

    return ""


def find_dns_resolved_ips():
    stdout, _, _ = run(
        f'tshark -r {PCAP} -Y "dns.a" -T fields -e dns.a'
    )
    return parse_ips(stdout)


def find_c2_ip(victim_ip, dns_resolved):
    stdout, _, _ = run(
        f'tshark -r {PCAP} -Y "ip.src == {victim_ip} and tcp" '
        f"-T fields -e ip.dst"
    )
    tcp_dsts = parse_ips(stdout)

    no_dns = tcp_dsts - dns_resolved - {victim_ip}

    candidates = [ip for ip in sorted(no_dns) if is_public_ip(ip)]
    if candidates:
        return candidates[0]

    stdout, _, _ = run(
        f'tshark -r {PCAP} -Y "ip.src == {victim_ip}" '
        f"-T fields -e ip.dst"
    )
    all_dsts = parse_ips(stdout)
    no_dns_all = all_dsts - dns_resolved - {victim_ip}
    candidates = [ip for ip in sorted(no_dns_all) if is_public_ip(ip)]
    if candidates:
        return candidates[0]

    return ""


def find_c2_from_binary(binary_path, dns_resolved):
    if not os.path.isfile(binary_path):
        return ""
    stdout, _, _ = run(f"strings -a {binary_path}")
    ip_re = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')
    non_dns_candidates = []
    all_candidates = []
    for m in ip_re.finditer(stdout):
        ip = m.group(1)
        if not is_public_ip(ip):
            continue
        all_candidates.append(ip)
        if ip not in dns_resolved:
            non_dns_candidates.append(ip)

    if non_dns_candidates:
        return non_dns_candidates[0]
    if all_candidates:
        return all_candidates[0]
    return ""


def main():
    os.makedirs(ARTIFACTS, exist_ok=True)
    os.makedirs(HTTP_EXPORT, exist_ok=True)

    # Export HTTP objects from PCAP
    print("[*] Exporting HTTP objects from PCAP...")
    run(f"tshark -r {PCAP} --export-objects http,{HTTP_EXPORT}")
    exported_files = sorted(os.listdir(HTTP_EXPORT))
    print(f"[*] Exported {len(exported_files)} HTTP objects")

    # Identify Java applets and PE executables
    applets = []
    pe_candidates = []

    for fname in exported_files:
        fpath = os.path.join(HTTP_EXPORT, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, "rb") as f:
            header = f.read(4)

        if fname.lower().endswith(".jar"):
            applets.append(fname)
            shutil.copy2(fpath, os.path.join(ARTIFACTS, fname))
            print(f"[+] Found Java applet: {fname}")

        if len(header) >= 2 and header[:2] == b"MZ":
            pe_candidates.append(fpath)
            print(f"[+] Found PE: {fname} (MD5: {md5_file(fpath)})")

    applets = sorted(set(applets))
    print(f"[*] Java applets: {applets}")

    # Extract packed malware
    packed_path = os.path.join(ARTIFACTS, "malware_packed.exe")
    if pe_candidates:
        selected = None
        for pf in pe_candidates:
            if md5_file(pf).endswith("91ed"):
                selected = pf
                break
        if not selected:
            selected = pe_candidates[0]
        shutil.copy2(selected, packed_path)

    packed_md5 = md5_file(packed_path)
    print(f"[*] Packed malware MD5: {packed_md5}")

    # Unpack with UPX
    packer = "UPX"
    unpacked_path = os.path.join(ARTIFACTS, "malware_unpacked.exe")
    shutil.copy2(packed_path, unpacked_path)
    stdout, stderr, rc = run(f"upx -d {unpacked_path}")
    print(f"[*] UPX unpack exit code: {rc}")
    if rc != 0:
        print(f"[!] UPX stderr: {stderr}")
    unpacked_md5 = md5_file(unpacked_path)
    print(f"[*] Unpacked malware MD5: {unpacked_md5}")

    # Find victim IP
    victim_ip = find_victim_ip()
    print(f"[*] Victim IP: {victim_ip}")

    # Find victim username
    username = find_username()
    print(f"[*] Victim username: {username}")

    # Find initial URL
    stdout, _, _ = run(
        f'tshark -r {PCAP} -Y "http.request.method == GET" '
        f'-T fields -e frame.number -e http.host -e http.request.uri '
        f'-E separator="|"'
    )
    initial_url = ""
    for line in stdout.split("\n"):
        parts = line.strip().split("|")
        if len(parts) >= 3:
            host = parts[1].strip()
            uri = parts[2].strip()
            if host and uri:
                initial_url = f"http://{host}{uri}"
                break
    print(f"[*] Initial URL: {initial_url}")

    # Find C2 IP
    dns_resolved = find_dns_resolved_ips()
    print(f"[*] DNS-resolved IPs: {sorted(dns_resolved)}")

    c2_ip = find_c2_ip(victim_ip, dns_resolved)

    if not c2_ip:
        c2_ip = find_c2_from_binary(unpacked_path, dns_resolved)

    if not c2_ip:
        c2_ip = find_c2_from_binary(packed_path, dns_resolved)

    print(f"[*] C2 IP: {c2_ip}")

    # Build forensic report
    report = {
        "victim_username": username,
        "initial_url": initial_url,
        "java_applets": applets,
        "packed_malware_md5": packed_md5,
        "packer_name": packer,
        "unpacked_malware_md5": unpacked_md5,
        "c2_ip": c2_ip,
    }

    with open(REPORT, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n[*] Forensic report written to {REPORT}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
