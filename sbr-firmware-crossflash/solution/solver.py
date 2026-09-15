#!/usr/bin/env python3
"""Solve the SBR crossflash task by reverse-engineering the binary format
and constructing the target SBR with all required output artifacts.

"""
import struct
import json
import os
import subprocess


CHECKSUM_TARGET = 0x5B


def analyze_sbr(path):
    """Parse key fields from an SBR binary."""
    with open(path, 'rb') as f:
        data = f.read()
    assert len(data) == 256

    vid = struct.unpack_from('<H', data, 0x0C)[0]
    pid = struct.unpack_from('<H', data, 0x0E)[0]
    mode = data[0x10]
    phy_lane = data[0x12]
    svid = struct.unpack_from('<H', data, 0x14)[0]
    spid = struct.unpack_from('<H', data, 0x16)[0]
    sas = data[0xD8:0xE0]

    pri_ok = sum(data[0x00:0x4C]) % 256 == CHECKSUM_TARGET
    mirror_ok = data[0x00:0x4C] == data[0x4C:0x98]
    sas_ok = sum(data[0xD8:0xF0]) % 256 == CHECKSUM_TARGET

    return {
        'vid': vid, 'pid': pid, 'mode': mode, 'phy_lane': phy_lane,
        'svid': svid, 'spid': spid, 'sas': sas.hex(':'),
        'pri_cksum_ok': pri_ok, 'mirror_ok': mirror_ok, 'sas_cksum_ok': sas_ok
    }


def audit_sample(dumps_dir, filename):
    """Perform structural integrity audit on a single SBR dump."""
    path = os.path.join(dumps_dir, filename)
    with open(path, 'rb') as f:
        data = f.read()

    issues = []

    if len(data) != 256:
        issues.append(f"Unexpected file size: {len(data)} bytes (expected 256)")
        return {"filename": filename, "valid": False, "issues": issues}

    # Check primary region checksum: sum(0x00..0x4B) mod 256 should equal 0x5B
    pri_sum = sum(data[0x00:0x4C]) % 256
    if pri_sum != CHECKSUM_TARGET:
        issues.append(
            f"Primary checksum invalid: sum(0x00..0x4B) mod 256 = "
            f"0x{pri_sum:02X}, expected 0x{CHECKSUM_TARGET:02X}"
        )

    # Check mirror consistency: bytes 0x4C-0x97 should equal 0x00-0x4B
    primary = data[0x00:0x4C]
    mirror = data[0x4C:0x98]
    if primary != mirror:
        mismatches = sum(1 for i in range(len(primary)) if primary[i] != mirror[i])
        issues.append(
            f"Mirror region mismatch: {mismatches} byte(s) at 0x4C-0x97 "
            f"differ from primary region 0x00-0x4B"
        )

    # Check SAS region checksum: sum(0xD8..0xEF) mod 256 should equal 0x5B
    sas_sum = sum(data[0xD8:0xF0]) % 256
    if sas_sum != CHECKSUM_TARGET:
        issues.append(
            f"SAS checksum invalid: sum(0xD8..0xEF) mod 256 = "
            f"0x{sas_sum:02X}, expected 0x{CHECKSUM_TARGET:02X}"
        )

    return {"filename": filename, "valid": len(issues) == 0, "issues": issues}


def main():
    dumps_dir = '/app/dumps'
    output_dir = '/app/output'
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Read manifest and analyze all SBR dumps
    with open(os.path.join(dumps_dir, 'manifest.json')) as f:
        manifest = json.load(f)

    print("=== Analyzing SBR samples ===")
    for sample in manifest['samples']:
        fname = sample['filename']
        info = analyze_sbr(os.path.join(dumps_dir, fname))
        print(f"\n{fname} ({sample['vendor']} {sample['model']}):")
        print(f"  VID=0x{info['vid']:04X} PID=0x{info['pid']:04X} "
              f"Mode=0x{info['mode']:02X} PHY=0x{info['phy_lane']:02X}")
        print(f"  SubVID=0x{info['svid']:04X} SubPID=0x{info['spid']:04X}")
        print(f"  SAS={info['sas']}")
        print(f"  Checksums: primary={'OK' if info['pri_cksum_ok'] else 'BAD'} "
              f"mirror={'OK' if info['mirror_ok'] else 'BAD'} "
              f"sas={'OK' if info['sas_cksum_ok'] else 'BAD'}")

    # Step 2: Integrity audit
    print("\n=== Integrity Audit ===")
    audit_results = []
    for sample in manifest['samples']:
        result = audit_sample(dumps_dir, sample['filename'])
        audit_results.append(result)
        status = "VALID" if result['valid'] else f"INVALID: {result['issues']}"
        print(f"  {sample['filename']}: {status}")

    audit_path = os.path.join(output_dir, 'integrity_audit.json')
    with open(audit_path, 'w') as f:
        json.dump({"samples": audit_results}, f, indent=2)
    print("=== integrity_audit.json written ===")

    # Step 3: Determine IT/IR parameters from valid reference
    ref_itir = analyze_sbr(os.path.join(dumps_dir, 'supermicro_itir.bin'))
    itir_pid = ref_itir['pid']   # 0x0072
    itir_mode = ref_itir['mode']  # 0x00
    phy_lane_full = ref_itir['phy_lane']  # 0x07
    print(f"\n=== IT/IR: PID=0x{itir_pid:04X} mode=0x{itir_mode:02X} PHY=0x{phy_lane_full:02X} ===")

    # Step 4: Modify the Fujitsu SBR
    fujitsu_path = os.path.join(dumps_dir, 'fujitsu_d2607_original.bin')
    with open(fujitsu_path, 'rb') as f:
        sbr = bytearray(f.read())

    print("\n=== Modifying Fujitsu SBR ===")

    # Set IT/IR PCI Product ID
    struct.pack_into('<H', sbr, 0x0E, itir_pid)

    # Set interface mode to IT/IR
    sbr[0x10] = itir_mode

    # Set PHY lane enable for all 8 ports
    sbr[0x12] = phy_lane_full

    # Recompute primary checksum at 0x4B
    s = sum(sbr[0x00:0x4B]) % 256
    sbr[0x4B] = (CHECKSUM_TARGET - s) % 256
    print(f"  Primary checksum: 0x{sbr[0x4B]:02X}")

    # Update Mfg Page 2 mirror (copy 0x00-0x4B to 0x4C-0x97)
    sbr[0x4C:0x98] = sbr[0x00:0x4C]

    # Verify
    assert sum(sbr[0x00:0x4C]) % 256 == CHECKSUM_TARGET
    assert sbr[0x00:0x4C] == sbr[0x4C:0x98]
    assert sum(sbr[0xD8:0xF0]) % 256 == CHECKSUM_TARGET
    print(f"  SAS preserved: {sbr[0xD8:0xE0].hex(':')}")

    # Step 5: Write target.bin
    target_bin_path = os.path.join(output_dir, 'target.bin')
    with open(target_bin_path, 'wb') as f:
        f.write(bytes(sbr))
    print(f"=== target.bin written ===")

    # Step 6: xxd hex dump
    target_hex_path = os.path.join(output_dir, 'target.hex')
    result = subprocess.run(["xxd", target_bin_path], capture_output=True, text=True)
    assert result.returncode == 0, f"xxd failed: {result.stderr}"
    with open(target_hex_path, 'w') as f:
        f.write(result.stdout)
    print("=== target.hex written ===")

    # Step 7: cmp -l diff report
    diff_path = os.path.join(output_dir, 'diff_report.txt')
    result = subprocess.run(
        ["cmp", "-l", fujitsu_path, target_bin_path],
        capture_output=True, text=True
    )
    with open(diff_path, 'w') as f:
        f.write(result.stdout)
    print("=== diff_report.txt written ===")

    # Step 8: field_map.json
    field_map = {
        "fields": [
            {"offset_hex": "0x00", "size_bytes": 12,
             "description": "PHY analog configuration (board-specific tuning)"},
            {"offset_hex": "0x0C", "size_bytes": 2,
             "description": "PCI Vendor ID (little-endian, 0x1000 = LSI Logic)"},
            {"offset_hex": "0x0E", "size_bytes": 2,
             "description": "PCI Product ID (little-endian, 0x0072=IT/IR, 0x0073=iMR)"},
            {"offset_hex": "0x10", "size_bytes": 1,
             "description": "Interface mode (0x00=IT/IR HBA, 0x10=iMR MegaRAID)"},
            {"offset_hex": "0x12", "size_bytes": 1,
             "description": "PHY lane enable (0x07=all 8 ports, 0x04=4 ports only)"},
            {"offset_hex": "0x14", "size_bytes": 2,
             "description": "Subsystem Vendor ID (little-endian)"},
            {"offset_hex": "0x16", "size_bytes": 2,
             "description": "Subsystem Product ID (little-endian)"},
            {"offset_hex": "0x18", "size_bytes": 40,
             "description": "Reserved region (must be zeroed)"},
            {"offset_hex": "0x40", "size_bytes": 11,
             "description": "Electrical timing parameters (board-specific)"},
            {"offset_hex": "0x4B", "size_bytes": 1,
             "description": "Primary region checksum (sum of 0x00-0x4B mod 256 = 0x5B)"},
            {"offset_hex": "0x4C", "size_bytes": 76,
             "description": "Mfg Page 2 mirror (exact copy of bytes 0x00-0x4B)"},
            {"offset_hex": "0x98", "size_bytes": 64,
             "description": "Reserved region (must be zeroed)"},
            {"offset_hex": "0xD8", "size_bytes": 8,
             "description": "SAS World Wide Name (8-byte IEEE address)"},
            {"offset_hex": "0xE0", "size_bytes": 15,
             "description": "Reserved region (must be zeroed)"},
            {"offset_hex": "0xEF", "size_bytes": 1,
             "description": "SAS region checksum (sum of 0xD8-0xEF mod 256 = 0x5B)"},
            {"offset_hex": "0xF0", "size_bytes": 16,
             "description": "Reserved region (must be zeroed)"}
        ]
    }
    field_map_path = os.path.join(output_dir, 'field_map.json')
    with open(field_map_path, 'w') as f:
        json.dump(field_map, f, indent=2)
    print("=== field_map.json written ===")

    print("\nAll outputs generated successfully.")


if __name__ == '__main__':
    main()
