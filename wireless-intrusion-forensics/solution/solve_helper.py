#!/usr/bin/env python3
"""

Forensic analysis of 802.11 wireless intrusion from PCAP evidence.
Reconstructs the full attack, evaluates the attack technique, computes
effectiveness metrics, and creates detection filters.
"""

import subprocess
import json
import re
import base64
import os
from collections import Counter

PCAP = "/app/evidence08.pcap"
DEC_PCAP = "/app/evidence08-dec.pcap"
REPORT = "/app/assessment.json"


def run(cmd):
    """Execute a shell command and return stripped stdout."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=300
    )
    return result.stdout.strip()


def decode_ssid(raw_ssid):
    """Decode SSID from tshark output. Newer tshark versions output
    wlan.ssid as hex bytes. Detect and decode hex-encoded SSIDs."""
    if not raw_ssid:
        return raw_ssid
    if re.fullmatch(r'[0-9a-fA-F]+', raw_ssid) and len(raw_ssid) % 2 == 0:
        try:
            decoded = bytes.fromhex(raw_ssid).decode('ascii')
            if all(32 <= ord(c) < 127 for c in decoded):
                return decoded
        except (ValueError, UnicodeDecodeError):
            pass
    return raw_ssid


def main():
    os.chdir("/app")

    # ---- Step 1: Identify target AP from beacon frames ----
    beacon_raw = run(
        f"tshark -r {PCAP} -Y 'wlan.fc.type_subtype == 0x08' "
        f"-T fields -e wlan.ssid -e wlan.bssid 2>/dev/null"
    )
    bssid_counter = Counter()
    ssid_for_bssid = {}
    for line in beacon_raw.split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip():
            b = parts[1].strip().lower()
            bssid_counter[b] += 1
            if parts[0].strip():
                ssid_for_bssid[b] = parts[0].strip()
    bssid = bssid_counter.most_common(1)[0][0]
    ssid_raw = ssid_for_bssid.get(bssid, "")
    ssid = decode_ssid(ssid_raw)
    print(f"[+] Target AP: SSID={ssid}, BSSID={bssid}")

    # ---- Step 2: Capture duration ----
    capinfo = run(f"capinfos {PCAP} 2>/dev/null")
    dur_match = re.search(r"Capture duration:\s+(\d+(?:\.\d+)?)", capinfo)
    duration = round(float(dur_match.group(1))) if dur_match else 0
    print(f"[+] Capture duration: {duration}s")

    # ---- Step 3: Count WEP-encrypted data frames ----
    wep_count_str = run(
        f"tshark -r {PCAP} -Y '(wlan.fc.type_subtype == 0x20) && "
        f"(wlan.fc.protected == 1) && (wlan.bssid == {bssid})' "
        f"2>/dev/null | wc -l"
    )
    total_wep_frames = int(wep_count_str) if wep_count_str.strip() else 0
    print(f"[+] WEP data frames: {total_wep_frames}")

    # ---- Step 4: Extract IVs with source MACs ----
    iv_raw = run(
        f"tshark -r {PCAP} -Y '(wlan.bssid == {bssid}) && wlan.wep.iv' "
        f"-T fields -e wlan.sa -e wlan.wep.iv 2>/dev/null"
    )
    mac_iv_pairs = []
    for line in iv_raw.split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
            mac_iv_pairs.append((parts[0].strip().lower(), parts[1].strip()))

    all_unique_ivs = set(iv for _, iv in mac_iv_pairs)
    total_unique_ivs = len(all_unique_ivs)
    print(f"[+] Total unique IVs: {total_unique_ivs}")

    # ---- Step 5: Identify attacker (non-AP station with most IV traffic) ----
    non_ap_counts = Counter(mac for mac, _ in mac_iv_pairs if mac != bssid)
    attacker_mac = non_ap_counts.most_common(1)[0][0]
    print(f"[+] Attacker MAC: {attacker_mac}")

    attacker_ivs = set(iv for mac, iv in mac_iv_pairs if mac == attacker_mac)
    attacker_unique_ivs = len(attacker_ivs)
    print(f"[+] Attacker unique IVs: {attacker_unique_ivs}")

    # Attacker IV share (percentage)
    attacker_iv_share = round((attacker_unique_ivs / total_unique_ivs) * 100, 1) if total_unique_ivs > 0 else 0.0
    print(f"[+] Attacker IV share: {attacker_iv_share}%")

    # ---- Step 6: Deauthentication frame analysis ----
    deauth_count_str = run(
        f"tshark -r {PCAP} -Y '(wlan.fc.type_subtype == 0x000c) && "
        f"(wlan.bssid == {bssid})' 2>/dev/null | wc -l"
    )
    deauth_frame_count = int(deauth_count_str) if deauth_count_str.strip() else 0
    print(f"[+] Deauth frames on BSS: {deauth_frame_count}")

    # ---- Step 7: Evaluate attack technique ----
    # ARP replay produces uniform small frames (~68 bytes on wire, ~36 byte LLC/SNAP payload)
    # chopchop produces variable-size frames
    # fragmentation uses fragment flags
    # caffe-latte targets the client, not the AP
    #
    # Check frame size distribution of attacker's data frames
    size_raw = run(
        f"tshark -r {PCAP} -Y '(wlan.fc.type_subtype == 0x20) && "
        f"(wlan.fc.protected == 1) && (wlan.sa == {attacker_mac}) && "
        f"(wlan.bssid == {bssid})' -T fields -e frame.len 2>/dev/null"
    )
    sizes = []
    for line in size_raw.split("\n"):
        line = line.strip()
        if line and line.isdigit():
            sizes.append(int(line))

    # Analyze size distribution
    if sizes:
        size_counter = Counter(sizes)
        most_common_size, most_common_count = size_counter.most_common(1)[0]
        uniformity = most_common_count / len(sizes)
        print(f"[+] Most common attacker frame size: {most_common_size} ({uniformity*100:.1f}% of frames)")

        # Also check traffic direction: ARP replay goes TO the AP (wlan.da == bssid)
        to_ap_count_str = run(
            f"tshark -r {PCAP} -Y '(wlan.fc.type_subtype == 0x20) && "
            f"(wlan.fc.protected == 1) && (wlan.sa == {attacker_mac}) && "
            f"(wlan.da == {bssid})' 2>/dev/null | wc -l"
        )
        to_ap_count = int(to_ap_count_str) if to_ap_count_str.strip() else 0
        to_ap_ratio = to_ap_count / len(sizes) if sizes else 0

        # ARP replay signature: >80% uniform size AND >80% directed to AP
        if uniformity > 0.8 and to_ap_ratio > 0.8:
            attack_technique = "arp-replay"
            technique_evidence = (
                f"ARP replay identified: {uniformity*100:.1f}% of attacker frames are "
                f"{most_common_size} bytes (uniform ARP size), and {to_ap_ratio*100:.1f}% "
                f"are directed to the AP — characteristic of ARP request replay injection"
            )
        elif uniformity > 0.8:
            attack_technique = "arp-replay"
            technique_evidence = (
                f"ARP replay identified: {uniformity*100:.1f}% of attacker frames are "
                f"{most_common_size} bytes, indicating uniform ARP request injection"
            )
        else:
            # Fallback analysis for other techniques
            attack_technique = "chopchop"
            technique_evidence = (
                f"Variable frame sizes detected (most common: {most_common_size} bytes, "
                f"only {uniformity*100:.1f}% uniformity), suggesting chopchop attack"
            )
    else:
        attack_technique = "arp-replay"
        technique_evidence = "Unable to analyze frame sizes; defaulting to most common WEP attack technique"

    print(f"[+] Attack technique: {attack_technique}")
    print(f"[+] Evidence: {technique_evidence}")

    # ---- Step 8: Crack WEP key ----
    aircrack_out = run(f"aircrack-ng -b {bssid} {PCAP} 2>/dev/null")
    key_match = re.search(r"KEY FOUND!\s*\[\s*([0-9A-Fa-f:]+)\s*\]", aircrack_out)
    wep_key = key_match.group(1).upper() if key_match else ""
    print(f"[+] WEP key: {wep_key}")

    # ---- Step 9: Decrypt traffic ----
    decrypt_result = run(f"airdecap-ng -w {wep_key} {PCAP} 2>/dev/null")
    print(f"[+] Decryption result: {decrypt_result}")

    if not os.path.exists(DEC_PCAP):
        print("[-] ERROR: Decrypted PCAP not found!")
        with open(REPORT, "w") as f:
            json.dump({}, f)
        return

    # ---- Step 10: Extract admin credentials from HTTP Basic Auth ----
    admin_username = ""
    admin_password = ""
    auth_raw = run(
        f"tshark -r {DEC_PCAP} -Y 'http.authorization' "
        f"-T fields -e http.authorization 2>/dev/null"
    )
    for line in auth_raw.split("\n"):
        line = line.strip()
        if "Basic " in line:
            b64_part = line.split("Basic ")[-1].strip()
            b64_part = b64_part.split(",")[0].strip()
            try:
                decoded = base64.b64decode(b64_part).decode("utf-8", errors="replace")
                if ":" in decoded:
                    admin_username, admin_password = decoded.split(":", 1)
                    print(f"[+] Admin credentials: {admin_username}:{admin_password}")
                    break
            except Exception as e:
                print(f"[-] Base64 decode error: {e}")

    # ---- Step 11: Extract new admin passphrase from HTTP POST data ----
    new_passphrase = ""

    # Approach A: tshark urlencoded form fields
    form_raw = run(
        f'tshark -r {DEC_PCAP} -Y \'http.request.method == "POST"\' '
        f"-T fields -e urlencoded-form.key -e urlencoded-form.value "
        f"2>/dev/null"
    )
    if form_raw:
        for line in form_raw.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                keys = parts[0].split(",")
                values = parts[1].split(",")
                for i, key in enumerate(keys):
                    kl = key.lower().strip()
                    if "passwd" in kl or "passphrase" in kl or "password" in kl:
                        if i < len(values):
                            candidate = values[i].strip()
                            if candidate and candidate.lower() != admin_password.lower():
                                new_passphrase = candidate
                                break
                if new_passphrase:
                    break

    # Approach B: tshark http.file_data for POST bodies
    if not new_passphrase:
        post_body = run(
            f'tshark -r {DEC_PCAP} -Y \'http.request.method == "POST"\' '
            f"-T fields -e http.file_data 2>/dev/null"
        )
        if post_body:
            import urllib.parse
            for line in post_body.split("\n"):
                try:
                    decoded_line = urllib.parse.unquote(line)
                except Exception:
                    decoded_line = line
                match = re.search(
                    r"(?:http_passwd|passphrase|password)=([^&\s\r\n]+)",
                    decoded_line, re.IGNORECASE,
                )
                if match:
                    candidate = match.group(1)
                    if candidate.lower() != admin_password.lower():
                        new_passphrase = candidate
                        break

    # Approach C: raw strings in decrypted PCAP
    if not new_passphrase:
        strings_out = run(f"strings {DEC_PCAP}")
        for line in strings_out.split("\n"):
            match = re.search(
                r"(?:http_passwd|passphrase|password)=([^&\s\r\n]+)",
                line, re.IGNORECASE,
            )
            if match:
                candidate = match.group(1)
                if candidate.lower() != (admin_password or "").lower():
                    new_passphrase = candidate
                    break

    print(f"[+] New admin passphrase: {new_passphrase}")

    # ---- Step 12: Create detection filters ----
    deauth_detection_filter = (
        f"(wlan.fc.type_subtype == 0x000c) && (wlan.bssid == {bssid})"
    )
    replay_detection_filter = (
        f"(wlan.fc.type_subtype == 0x0020) && (wlan.fc.protected == 1) && "
        f"(wlan.sa == {attacker_mac}) && (wlan.bssid == {bssid})"
    )
    print(f"[+] Deauth detection filter: {deauth_detection_filter}")
    print(f"[+] Replay detection filter: {replay_detection_filter}")

    # ---- Step 13: Write assessment report ----
    assessment = {
        "ssid": ssid,
        "bssid": bssid,
        "wep_key": wep_key,
        "attacker_mac": attacker_mac,
        "attack_technique": attack_technique,
        "technique_evidence": technique_evidence,
        "capture_duration_seconds": duration,
        "total_wep_data_frames": total_wep_frames,
        "total_unique_ivs": total_unique_ivs,
        "attacker_unique_ivs": attacker_unique_ivs,
        "attacker_iv_share": attacker_iv_share,
        "deauth_frame_count": deauth_frame_count,
        "admin_username": admin_username,
        "admin_password": admin_password,
        "new_admin_passphrase": new_passphrase,
        "deauth_detection_filter": deauth_detection_filter,
        "replay_detection_filter": replay_detection_filter,
    }

    with open(REPORT, "w") as f:
        json.dump(assessment, f, indent=2)

    print(f"\n[+] Assessment written to {REPORT}")
    print(json.dumps(assessment, indent=2))


if __name__ == "__main__":
    main()
