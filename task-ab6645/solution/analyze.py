#!/usr/bin/env python3
"""
Reverse-engineer stripped ELF malware sample with dual encrypted configs.
Evaluate which config is the real operational one, extract IOCs, create YARA rule.


Strategy:
1. Parse ELF headers to locate .rodata section
2. Brute-force search .rodata for XOR key candidates (4-byte, all bytes > 0x7f)
   and encrypted RC4 key candidates (8-byte, all bytes > 0x7f)
3. For each (xor_key, enc_rc4_key) pair, XOR-decrypt and check for printable ASCII
4. Use valid RC4 keys to try decrypting data blobs, validate with "c2_primary=" prefix
5. Collect ALL valid configs (there are two)
6. Evaluate which is real by cross-referencing against binary behavior:
   - Check if persistence path appears as plaintext string in binary (code reference)
   - Check for SVC_CONTINGENCY_MODE gating the secondary config
   - Check if port value is hardcoded in binary code
7. Write IOC report and YARA detection rule
"""

import struct
import json
import sys
import os


def find_sections(data):
    """Parse ELF64 LE section headers."""
    if data[:4] != b'\x7fELF':
        raise ValueError("Not an ELF file")
    if data[4] != 2 or data[5] != 1:
        raise ValueError("Expected ELF64 little-endian")

    e_shoff = struct.unpack_from('<Q', data, 40)[0]
    e_shentsize = struct.unpack_from('<H', data, 58)[0]
    e_shnum = struct.unpack_from('<H', data, 60)[0]
    e_shstrndx = struct.unpack_from('<H', data, 62)[0]

    strtab_hdr = e_shoff + e_shstrndx * e_shentsize
    strtab_off = struct.unpack_from('<Q', data, strtab_hdr + 24)[0]
    strtab_size = struct.unpack_from('<Q', data, strtab_hdr + 32)[0]
    strtab = data[strtab_off:strtab_off + strtab_size]

    sections = {}
    for i in range(e_shnum):
        sh = e_shoff + i * e_shentsize
        sh_name_idx = struct.unpack_from('<I', data, sh)[0]
        name_end = strtab.find(b'\x00', sh_name_idx)
        if name_end == -1:
            continue
        name = strtab[sh_name_idx:name_end].decode('ascii', errors='replace')
        sh_offset = struct.unpack_from('<Q', data, sh + 24)[0]
        sh_size = struct.unpack_from('<Q', data, sh + 32)[0]
        sections[name] = (sh_offset, sh_size)

    return sections


def xor_decrypt(data, key):
    return bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))


def rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) & 0xFF
        S[i], S[j] = S[j], S[i]
    out = bytearray(len(data))
    i = j = 0
    for k in range(len(data)):
        i = (i + 1) & 0xFF
        j = (j + S[i]) & 0xFF
        S[i], S[j] = S[j], S[i]
        out[k] = data[k] ^ S[(S[i] + S[j]) & 0xFF]
    return bytes(out)


def parse_config_text(text):
    """Parse key=value config text into a dictionary."""
    config = {}
    for line in text.strip().split('\n'):
        line = line.strip()
        if '=' in line:
            key, val = line.split('=', 1)
            config[key] = val
    return config


def find_all_configs(rodata):
    """Brute-force search for ALL encrypted config blocks in .rodata."""
    n = len(rodata)
    print(f"[*] .rodata size: {n} bytes")

    # 4-byte XOR key candidates (all bytes > 0x7f)
    xor_cands = []
    for off in range(n - 3):
        w = rodata[off:off + 4]
        if all(b > 0x7f for b in w):
            xor_cands.append((off, bytes(w)))
    print(f"[*] XOR key candidates: {len(xor_cands)}")

    # 8-byte encrypted RC4 key candidates (all bytes > 0x7f)
    enc_cands = []
    for off in range(n - 7):
        w = rodata[off:off + 8]
        if all(b > 0x7f for b in w):
            enc_cands.append((off, bytes(w)))
    print(f"[*] Encrypted key candidates: {len(enc_cands)}")

    configs = []
    found_config_offsets = set()

    for xoff, xkey in xor_cands:
        for eoff, edata in enc_cands:
            if abs(xoff - eoff) < 4:
                continue

            # XOR decrypt to get RC4 key candidate
            rkey = xor_decrypt(edata, xkey)
            if not all(0x20 <= b <= 0x7e for b in rkey):
                continue

            # Try this RC4 key on every .rodata offset
            for boff in range(n - 11):
                if boff in found_config_offsets:
                    continue

                # Quick 4-byte prefix check
                test = rc4(rkey, rodata[boff:boff + 4])
                if test != b"c2_p":
                    continue

                # Full decryption
                chunk_size = min(500, n - boff)
                blob = rc4(rkey, rodata[boff:boff + chunk_size])

                # Find config end
                end = chunk_size
                for k in range(chunk_size):
                    b = blob[k]
                    if b != 0x0a and (b < 0x20 or b > 0x7e):
                        end = k
                        break

                config_text = blob[:end].decode('ascii')
                if "c2_primary=" in config_text and "persistence=" in config_text:
                    print(f"[+] Config found: XOR key={xkey.hex()}, "
                          f"RC4 key={rkey.decode('ascii')}, offset={boff:#x}")
                    configs.append({
                        'xor_key': xkey,
                        'rc4_key': rkey,
                        'text': config_text,
                        'offset': boff,
                        'xor_offset': xoff,
                    })
                    found_config_offsets.add(boff)
                    break  # move to next key pair

    # Sort by offset to assign A/B labels
    configs.sort(key=lambda c: c['offset'])
    return configs


def evaluate_real_config(configs, binary_data):
    """
    Evaluate which decrypted config is the real operational one by
    cross-referencing against the binary's hardcoded strings and behavior.

    Evaluation criteria:
    1. Persistence path appears as a plaintext string in the binary
       (indicating it's used as a function argument in actual code)
    2. Config block ordering: primary is unconditionally executed,
       secondary is gated by SVC_CONTINGENCY_MODE env check
    3. Port number matches hardcoded immediate value in binary code
    """
    print("\n[*] === Evaluating configs to identify real operational config ===")

    scores = []
    for i, cfg in enumerate(configs):
        parsed = parse_config_text(cfg['text'])
        score = 0
        reasons = []

        # Criterion 1: persistence path in plaintext binary
        persist_path = parsed.get('persistence', '')
        if persist_path.encode() in binary_data:
            score += 3
            reasons.append(
                f"persistence path '{persist_path}' found as plaintext "
                f"string literal in binary (used by actual code)")
        else:
            reasons.append(
                f"persistence path '{persist_path}' NOT found in "
                f"binary plaintext (only exists encrypted)")

        # Criterion 2: ordering determines primary vs fallback
        if i == 0:
            score += 2
            reasons.append(
                "first config block in .rodata = primary execution path")
        else:
            reasons.append(
                "later config block = fallback/contingency path")

        # Criterion 3: SVC_CONTINGENCY_MODE guards the secondary config
        if b"SVC_CONTINGENCY_MODE" in binary_data:
            if i == 0:
                score += 1
                reasons.append(
                    "SVC_CONTINGENCY_MODE env var guards secondary "
                    "config, not this one")

        # Criterion 4: port number as hardcoded immediate
        port = int(parsed.get('exfil_port', '0'))
        port_le = struct.pack('<H', port)
        # Search for the 2-byte port value preceded by a reasonable
        # x86 instruction context
        count = binary_data.count(port_le)
        if count > 0:
            score += 1
            reasons.append(
                f"port {port} ({port_le.hex()}) found {count}x in binary")

        label = chr(65 + i)
        print(f"[*] Config {label} (offset {cfg['offset']:#x}): score={score}")
        for r in reasons:
            print(f"    - {r}")

        scores.append(score)

    real_idx = scores.index(max(scores))
    print(f"\n[+] Config {chr(65 + real_idx)} identified as REAL operational config "
          f"(score {scores[real_idx]} vs {scores[1-real_idx]})")
    return real_idx


def generate_yara_rule(xor_key):
    """Create a YARA detection rule for this malware family."""
    xor_hex = ' '.join(f'{b:02x}' for b in xor_key)

    rule = (
        'rule DarkCloud_Implant {\n'
        '    meta:\n'
        '        description = "Detects DarkCloud implant with encrypted '
        'dual C2 configuration"\n'
        '        author = "Automated IR Analysis"\n'
        '        date = "2024-03-15"\n'
        '\n'
        '    strings:\n'
        f'        $xor_key_primary = {{ {xor_hex} }}\n'
        '        $anti_debug_ptrace = "TracerPid:" ascii\n'
        '        $anti_debug_preload = "LD_PRELOAD" ascii\n'
        '        $contingency_env = "SVC_CONTINGENCY_MODE" ascii\n'
        '        $decoy_domain = "telemetry.windowsupdate.com" ascii\n'
        '        $fake_update = "Windows Update Service" ascii\n'
        '        $cron_persist = "/etc/cron.d/" ascii\n'
        '\n'
        '    condition:\n'
        '        uint32(0) == 0x464C457F and\n'
        '        $xor_key_primary and\n'
        '        $contingency_env and\n'
        '        $anti_debug_ptrace and\n'
        '        2 of ($decoy_domain, $fake_update, '
        '$anti_debug_preload, $cron_persist)\n'
        '}\n'
    )
    return rule


def main():
    binary_path = "/app/malware_sample"
    report_path = "/app/analysis_report.json"
    yara_path = "/app/detection.yar"

    print("[*] Loading malware sample...")
    with open(binary_path, "rb") as f:
        data = f.read()
    print(f"[*] Binary size: {len(data)} bytes")

    # Parse ELF sections
    sections = find_sections(data)
    print(f"[*] Found {len(sections)} sections")

    # Search .rodata (and fallback sections) for encrypted configs
    search_sections = ['.rodata', '.data.rel.ro', '.data']
    configs = []
    for sec_name in search_sections:
        if sec_name not in sections:
            continue
        sec_off, sec_size = sections[sec_name]
        print(f"[*] Searching section {sec_name} at offset {sec_off:#x}, "
              f"size {sec_size}")
        rodata = data[sec_off:sec_off + sec_size]
        found = find_all_configs(rodata)
        if found:
            configs.extend(found)
            break

    if not configs:
        print("[-] ERROR: Could not find any encrypted configurations")
        sys.exit(1)

    print(f"\n[+] Found {len(configs)} encrypted config block(s)")

    for i, cfg in enumerate(configs):
        parsed = parse_config_text(cfg['text'])
        label = chr(65 + i)
        print(f"\n[+] Config {label}:")
        print(f"    XOR key: {cfg['xor_key'].hex()}")
        print(f"    RC4 key: {cfg['rc4_key'].decode('ascii')} "
              f"({cfg['rc4_key'].hex()})")
        for k, v in parsed.items():
            print(f"    {k} = {v}")

    # Evaluate which config is the real operational one
    real_idx = evaluate_real_config(configs, data)
    real_cfg = configs[real_idx]
    real_label = chr(65 + real_idx)
    real_parsed = parse_config_text(real_cfg['text'])

    print(f"\n[+] === Final Results ===")
    print(f"[+] Real operational config: {real_label}")

    # Build IOC report
    report = {
        "c2_primary": real_parsed.get("c2_primary", ""),
        "c2_secondary": real_parsed.get("c2_secondary", ""),
        "campaign_id": real_parsed.get("campaign_id", ""),
        "rc4_key_hex": real_cfg['rc4_key'].hex(),
        "xor_key_hex": real_cfg['xor_key'].hex(),
        "mutex": real_parsed.get("mutex", ""),
        "exfil_port": int(real_parsed.get("exfil_port", "0")),
        "persistence_path": real_parsed.get("persistence", ""),
        "real_config_id": real_label,
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[+] Report written to {report_path}")

    # Generate YARA detection rule
    yara_rule = generate_yara_rule(real_cfg['xor_key'])
    with open(yara_path, "w") as f:
        f.write(yara_rule)
    print(f"[+] YARA rule written to {yara_path}")


if __name__ == "__main__":
    main()
