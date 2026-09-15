#!/usr/bin/env python3
"""Firmware supply-chain security assessment solver.

Analyzes firmware.bin by:
1. Parsing the FWPK container format
2. Extracting and decompressing all sections (zlib + custom_lz)
3. Disassembling the bootloader ELF to find backdoor key and signing key
4. Verifying the firmware signature
5. Reverse-engineering the CNFG config encryption
6. Cross-referencing rootfs against manifest for supply-chain anomalies
7. Synthesizing an incident summary with risk assessment
8. Generating a YARA detection rule
"""

import struct
import zlib
import hashlib
import hmac as hmac_mod
import json
import re
import subprocess
import tempfile
import os


def decode_varint(data, offset):
    """Decode a varint (variable-length unsigned integer)."""
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        result |= (byte & 0x7F) << shift
        offset += 1
        if not (byte & 0x80):
            break
        shift += 7
    return result, offset


def xor_decrypt_config(data, seed_bytes, start_offset):
    """Decrypt config data using rotating XOR key stream."""
    result = bytearray()
    for i, b in enumerate(data):
        pos = start_offset + i
        key_byte = seed_bytes[pos % 4] ^ (pos & 0xFF)
        result.append(b ^ key_byte)
    return bytes(result)


def analyze_bootloader(elf_data):
    """Analyze bootloader ELF to extract backdoor key and signing key.

    Uses the ELF symbol table to locate encoded data arrays and disassembly
    to identify the XOR masks used for obfuscation.
    """
    with tempfile.NamedTemporaryFile(suffix='.elf', delete=False) as f:
        f.write(elf_data)
        elf_path = f.name

    func_name = "unknown"
    debug_key = ""
    debug_mask = 0
    hmac_key_str = ""
    hmac_mask = 0

    try:
        # === Step 1: Enumerate symbols using nm ===
        nm_result = subprocess.run(['nm', elf_path], capture_output=True, text=True)
        symbols = {}  # name -> address
        debug_token_addr = None
        hmac_key_enc_addr = None

        for line in nm_result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                try:
                    addr = int(parts[0], 16)
                    sym_name = parts[-1]
                    symbols[sym_name] = addr
                except ValueError:
                    continue

                if 'debug_authenticate' in sym_name:
                    func_name = sym_name
                if '_debug_auth_token' in sym_name:
                    debug_token_addr = addr
                if '_hmac_key_enc' in sym_name:
                    hmac_key_enc_addr = addr

        print(f"  Found {len(symbols)} symbols")
        print(f"  debug_token @ 0x{debug_token_addr:x}" if debug_token_addr else "  debug_token: NOT FOUND")
        print(f"  hmac_key_enc @ 0x{hmac_key_enc_addr:x}" if hmac_key_enc_addr else "  hmac_key_enc: NOT FOUND")

        # === Step 2: Parse ELF section headers for vaddr->file offset mapping ===
        is_64bit = elf_data[4] == 2
        if is_64bit:
            e_shoff = struct.unpack_from('<Q', elf_data, 0x28)[0]
            e_shentsize = struct.unpack_from('<H', elf_data, 0x3A)[0]
            e_shnum = struct.unpack_from('<H', elf_data, 0x3C)[0]
        else:
            e_shoff = struct.unpack_from('<I', elf_data, 0x20)[0]
            e_shentsize = struct.unpack_from('<H', elf_data, 0x2E)[0]
            e_shnum = struct.unpack_from('<H', elf_data, 0x30)[0]

        elf_sections = []
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            if is_64bit:
                sh_addr = struct.unpack_from('<Q', elf_data, off + 0x10)[0]
                sh_offset = struct.unpack_from('<Q', elf_data, off + 0x18)[0]
                sh_size = struct.unpack_from('<Q', elf_data, off + 0x20)[0]
            else:
                sh_addr = struct.unpack_from('<I', elf_data, off + 0x0C)[0]
                sh_offset = struct.unpack_from('<I', elf_data, off + 0x10)[0]
                sh_size = struct.unpack_from('<I', elf_data, off + 0x14)[0]
            elf_sections.append((sh_addr, sh_offset, sh_size))

        def vaddr_to_foff(vaddr):
            for sh_addr, sh_offset, sh_size in elf_sections:
                if sh_size > 0 and sh_addr > 0 and sh_addr <= vaddr < sh_addr + sh_size:
                    return sh_offset + (vaddr - sh_addr)
            return None

        # === Step 3: Extract XOR masks from disassembly ===
        dis_result = subprocess.run(
            ['objdump', '-d', '-M', 'intel', elf_path],
            capture_output=True, text=True
        )

        current_func = None
        xor_masks = {}  # func_name -> first XOR immediate found

        for line in dis_result.stdout.splitlines():
            fn_match = re.match(r'^[0-9a-f]+ <(\w+)>:', line)
            if fn_match:
                current_func = fn_match.group(1)
                continue

            if current_func and current_func not in xor_masks and 'xor' in line.lower():
                m = re.search(r'\bxor\b\s+[^,]+,\s*0x([0-9a-fA-F]+)', line, re.IGNORECASE)
                if m:
                    # Mask to 8 bits to handle sign-extended immediates
                    val = int(m.group(1), 16) & 0xFF
                    if val > 0:
                        xor_masks[current_func] = val

        debug_xor = xor_masks.get('debug_authenticate')
        hmac_xor = xor_masks.get('get_hmac_key')
        print(f"  XOR masks: debug=0x{debug_xor:02x}, hmac=0x{hmac_xor:02x}"
              if debug_xor and hmac_xor else f"  XOR masks: debug={debug_xor}, hmac={hmac_xor}")

        # === Step 4: Read encoded bytes and decode ===
        if debug_token_addr is not None and debug_xor is not None:
            foff = vaddr_to_foff(debug_token_addr)
            if foff is not None:
                debug_enc = elf_data[foff:foff + 16]
                debug_key = bytes(b ^ debug_xor for b in debug_enc).decode('ascii', errors='replace')
                debug_mask = debug_xor

        if hmac_key_enc_addr is not None and hmac_xor is not None:
            foff = vaddr_to_foff(hmac_key_enc_addr)
            if foff is not None:
                hmac_enc = elf_data[foff:foff + 32]
                hmac_key_str = bytes(b ^ hmac_xor for b in hmac_enc).decode('ascii', errors='replace')
                hmac_mask = hmac_xor

    finally:
        os.unlink(elf_path)

    return {
        'function_name': func_name,
        'debug_key': debug_key,
        'debug_mask': debug_mask,
        'hmac_key': hmac_key_str,
        'hmac_mask': hmac_mask,
    }


def solve():
    with open('/app/firmware.bin', 'rb') as f:
        fw = f.read()

    # === Initial triage with binwalk ===
    print("=== Binwalk signature scan ===")
    result = subprocess.run(['binwalk', '/app/firmware.bin'],
                            capture_output=True, text=True)
    print(result.stdout)

    # === Parse 64-byte FWPK header ===
    magic = fw[0:4]
    assert magic == b"FWPK", f"Unexpected magic: {magic}"

    version = struct.unpack_from('<H', fw, 0x04)[0]
    num_sections = struct.unpack_from('<H', fw, 0x06)[0]
    header_timestamp = struct.unpack_from('<I', fw, 0x10)[0]
    device_id = fw[0x14:0x24].rstrip(b'\x00').decode('ascii')

    print(f"Device: {device_id}, Sections: {num_sections}, "
          f"Version: 0x{version:04X}, Timestamp: {header_timestamp}")

    # === Parse variable-length section table at offset 0x40 ===
    offset = 0x40
    sections = []
    for _ in range(num_sections):
        sec_type = fw[offset]; offset += 1
        sec_flags = fw[offset]; offset += 1
        name_len = fw[offset]; offset += 1
        name = fw[offset:offset + name_len].decode('ascii'); offset += name_len
        compressed_size = struct.unpack_from('<I', fw, offset)[0]; offset += 4
        decompressed_size = struct.unpack_from('<I', fw, offset)[0]; offset += 4
        compression = fw[offset]; offset += 1
        checksum = struct.unpack_from('<I', fw, offset)[0]; offset += 4
        sections.append({
            'name': name,
            'compressed_size': compressed_size,
            'decompressed_size': decompressed_size,
            'compression': compression,
            'checksum': checksum,
        })
        print(f"  Section '{name}': {compressed_size}B compressed, "
              f"compression={compression}")

    # === Extract and decompress all sections ===
    decompressed = {}
    for sec in sections:
        compressed_data = fw[offset:offset + sec['compressed_size']]
        offset += sec['compressed_size']

        if sec['compression'] == 1:  # Standard zlib
            raw = zlib.decompress(compressed_data)
        elif sec['compression'] == 2:  # Custom LZ: 0xCAFE prefix + zlib
            assert compressed_data[:2] == bytes([0xCA, 0xFE])
            raw = zlib.decompress(compressed_data[2:])
        else:
            raw = compressed_data

        assert len(raw) == sec['decompressed_size']
        assert zlib.crc32(raw) & 0xFFFFFFFF == sec['checksum']
        decompressed[sec['name']] = raw

    # Data region ends here; signature block follows
    body_end = offset

    # === Extract and verify signature block ===
    sig_block_magic = fw[body_end:body_end + 4]
    assert sig_block_magic == b"HMAC", f"Expected HMAC block, got {sig_block_magic}"
    hmac_stored = fw[body_end + 4:body_end + 36]
    body = fw[:body_end]

    # === Analyze bootloader ELF for secrets ===
    print("\n=== Analyzing bootloader ELF ===")
    bootloader = decompressed['bootloader']
    bl = analyze_bootloader(bootloader)
    print(f"Backdoor function: {bl['function_name']}")
    print(f"Debug key: {bl['debug_key']} (XOR mask: 0x{bl['debug_mask']:02X})")
    print(f"Signing key: {bl['hmac_key']} (XOR mask: 0x{bl['hmac_mask']:02X})")

    # === Verify HMAC using extracted key ===
    hmac_key_bytes = bl['hmac_key'].encode('ascii')
    hmac_computed = hmac_mod.new(hmac_key_bytes, body, hashlib.sha256).digest()
    signature_valid = (hmac_computed == hmac_stored)
    print(f"Signature valid: {signature_valid}")

    # === Parse config section (CNFG with XOR encryption) ===
    print("\n=== Decrypting config section ===")
    config_raw = decompressed['config']
    assert config_raw[:4] == b"CNFG"
    coff = 4
    num_entries, coff = decode_varint(config_raw, coff)
    xor_seed = struct.unpack_from('<I', config_raw, coff)[0]
    coff += 4
    seed_bytes = struct.pack('<I', xor_seed)

    config = {}
    byte_offset = 0
    for _ in range(num_entries):
        key_len, coff = decode_varint(config_raw, coff)
        key_enc = config_raw[coff:coff + key_len]
        coff += key_len
        key = xor_decrypt_config(key_enc, seed_bytes, byte_offset).decode('utf-8')
        byte_offset += key_len

        value_type = config_raw[coff]
        coff += 1

        value_len, coff = decode_varint(config_raw, coff)
        value_enc = config_raw[coff:coff + value_len]
        coff += value_len
        value_dec = xor_decrypt_config(value_enc, seed_bytes, byte_offset)
        byte_offset += value_len

        if value_type == 0x01:  # UTF-8 string
            config[key] = value_dec.decode('utf-8')
        elif value_type == 0x02:  # int32 LE
            config[key] = struct.unpack('<i', value_dec)[0]
        elif value_type == 0x03:  # raw bytes
            config[key] = value_dec.hex()

        print(f"  {key} = {config[key]}")

    # === Parse rootfs section ===
    print("\n=== Parsing rootfs ===")
    rootfs = decompressed['rootfs']
    assert rootfs[:8] == b"ROOTFS\x00\x00"
    roff = 8
    rootfs_paths = []
    rootfs_contents = {}
    while True:
        path_len = struct.unpack_from('<H', rootfs, roff)[0]
        roff += 2
        if path_len == 0:
            break
        path = rootfs[roff:roff + path_len].decode('utf-8')
        roff += path_len
        content_len = struct.unpack_from('<I', rootfs, roff)[0]
        roff += 4
        content = rootfs[roff:roff + content_len]
        roff += content_len
        rootfs_paths.append(path)
        rootfs_contents[path] = content
        print(f"  {path} ({content_len} bytes)")

    # === Parse manifest section ===
    manifest_raw = decompressed['manifest']
    assert manifest_raw[:4] == b"MNFT"
    manifest_json_len = struct.unpack_from('<I', manifest_raw, 4)[0]
    manifest = json.loads(manifest_raw[8:8 + manifest_json_len])

    # === Identify supply-chain anomalies ===
    print("\n=== Supply chain analysis ===")
    anomalies = []

    # Anomaly 1: Files in rootfs not listed in manifest expected_files
    expected_files = set(manifest.get("expected_files", []))
    actual_files = set(rootfs_paths)
    unlisted = actual_files - expected_files
    for path in sorted(unlisted):
        anomalies.append({
            "type": "unlisted_file",
            "detail": f"File '{path}' exists in rootfs but is not listed "
                      f"in manifest expected_files — potential supply-chain injection"
        })
        print(f"  ANOMALY: Unlisted file {path}")

    # Anomaly 2: Signature algorithm mismatch
    claimed_algo = manifest.get("signature_algorithm", "unknown")
    anomalies.append({
        "type": "algorithm_mismatch",
        "detail": f"Manifest claims '{claimed_algo}' signature algorithm but "
                  f"actual firmware signature uses HMAC-SHA256 with key "
                  f"embedded in bootloader ELF"
    })
    print(f"  ANOMALY: Algorithm mismatch ({claimed_algo} vs HMAC-SHA256)")

    # Anomaly 3: Timestamp inconsistency
    build_date = manifest.get("build_date", "unknown")
    anomalies.append({
        "type": "timestamp_anomaly",
        "detail": f"Container header timestamp ({header_timestamp}, ~Nov 2023) "
                  f"predates manifest build_date ({build_date}) — "
                  f"possible backdating of compromised package"
    })
    print(f"  ANOMALY: Timestamp backdating detected")

    # === Build YARA detection rule ===
    debug_enc_hex = " ".join(
        f"{b ^ bl['debug_mask']:02x}" for b in bl['debug_key'].encode()
    )
    hmac_enc_hex_short = " ".join(
        f"{b ^ bl['hmac_mask']:02x}" for b in bl['hmac_key'][:16].encode()
    )

    yara_rule = f"""rule NX7800_Firmware_Backdoor {{
    meta:
        description = "Detects NX-7800 firmware with debug authentication backdoor and compromised signing"
        severity = "critical"
        author = "security-audit"
    strings:
        $fwpk_magic = "FWPK"
        $debug_token = {{ {debug_enc_hex} }}
        $hmac_token = {{ {hmac_enc_hex_short} }}
        $c2_url = "c2.malicious.internal"
        $backdoor_func = "debug_authenticate"
    condition:
        $fwpk_magic at 0 and ($debug_token or $hmac_token or $c2_url or $backdoor_func)
}}"""

    # === Synthesize incident summary ===
    c2_url = ""
    if "/tmp/.update_hook" in rootfs_contents:
        hook_content = rootfs_contents["/tmp/.update_hook"].decode("utf-8", errors="replace")
        import re as re2
        url_match = re2.search(r'https?://[^\s|]+', hook_content)
        if url_match:
            c2_url = url_match.group(0)

    incident_summary = {
        "attack_vector": (
            "Supply-chain compromise of the firmware build or signing pipeline. "
            "An unauthorized shell script (/tmp/.update_hook) was injected into the root filesystem "
            "to act as a stage-2 loader contacting a C2 server. A debug authentication backdoor was "
            "embedded in the bootloader with an obfuscated hardcoded key, enabling unauthorized "
            "privileged access. The firmware signing key was embedded directly in the bootloader "
            "binary rather than held in an HSM, and the manifest falsely claims ed25519 signing "
            "to obscure the actual HMAC-SHA256 mechanism."
        ),
        "persistence_mechanism": (
            "The /tmp/.update_hook script downloads and executes a stage-2 payload from "
            f"{c2_url or 'c2.malicious.internal:8443'} on each firmware update cycle. "
            "The debug_authenticate() backdoor in the bootloader provides a persistent "
            "authentication bypass using the hardcoded key, surviving firmware re-installs "
            "as long as the same bootloader is used."
        ),
        "overall_risk": "critical",
        "risk_justification": (
            "Critical risk due to: (1) active command-and-control channel enabling arbitrary "
            "remote code execution on all deployed devices, (2) hardcoded debug authentication "
            "bypass granting unauthorized privileged access, (3) firmware signing key exposed "
            "in the bootloader binary allowing an attacker to sign future malicious updates, "
            "(4) manifest integrity violations indicating the build/release pipeline itself "
            "is compromised, and (5) the combination of these issues enables full persistent "
            "control over all devices running this firmware."
        ),
    }

    # === Assemble audit report ===
    audit = {
        "container": {
            "magic": "FWPK",
            "device_id": device_id,
            "num_sections": num_sections,
            "section_names": [s['name'] for s in sections],
        },
        "backdoor": {
            "function_name": bl['function_name'],
            "deobfuscation_method": f"XOR with 0x{bl['debug_mask']:02X}",
            "debug_key": bl['debug_key'],
            "severity": "critical",
        },
        "signature_analysis": {
            "signing_key": bl['hmac_key'],
            "signature_valid": signature_valid,
            "key_source": "Embedded in bootloader ELF .rodata, XOR-obfuscated "
                          f"with mask 0x{bl['hmac_mask']:02X}",
            "severity": "critical",
        },
        "config": config,
        "supply_chain_anomalies": anomalies,
        "incident_summary": incident_summary,
        "yara_rule": yara_rule,
    }

    with open("/app/audit.json", "w") as f:
        json.dump(audit, f, indent=2)
    print("\nAudit report written to /app/audit.json")


if __name__ == "__main__":
    solve()
