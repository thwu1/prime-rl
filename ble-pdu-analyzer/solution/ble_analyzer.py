#!/usr/bin/env python3
"""
BLE Advertisement PDU Analyzer — Multi-Format Capture Decoder

Reads BLE advertisement channel PDU captures from three different file formats:
  - .hex : hex-encoded PDUs, one per line
  - .dat : base64-encoded PDUs, one per line
  - .bin : binary with 2-byte little-endian length prefix per PDU

Parses each PDU per Bluetooth Core Specification v5.4, detects violations,
and produces /app/diagnostic_report.json.
"""
import base64
import glob
import json
import os
import struct

# ---- Constants ----

PDU_TYPES = {
    0: "ADV_IND",
    1: "ADV_DIRECT_IND",
    2: "ADV_NONCONN_IND",
    3: "SCAN_REQ",
    4: "SCAN_RSP",
    5: "CONNECT_IND",
    6: "ADV_SCAN_IND",
}

MAX_PAYLOAD = {0: 37, 1: 12, 2: 37, 4: 37, 6: 37}

AD_TYPE_NAMES = {
    0x01: "Flags",
    0x02: "Incomplete List of 16-bit Service UUIDs",
    0x03: "Complete List of 16-bit Service UUIDs",
    0x06: "Incomplete List of 128-bit Service UUIDs",
    0x07: "Complete List of 128-bit Service UUIDs",
    0x08: "Shortened Local Name",
    0x09: "Complete Local Name",
    0x0A: "TX Power Level",
    0x16: "Service Data - 16-bit UUID",
    0x19: "Appearance",
    0xFF: "Manufacturer Specific Data",
}

# ---- File Format Readers ----


def read_hex_file(path):
    """Read hex-encoded PDUs, one per line."""
    pdus = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                pdus.append(bytes.fromhex(line))
    return pdus


def read_b64_file(path):
    """Read base64-encoded PDUs, one per line."""
    pdus = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                pdus.append(base64.b64decode(line))
    return pdus


def read_bin_file(path):
    """Read binary file with 2-byte LE length prefix per PDU."""
    pdus = []
    with open(path, "rb") as f:
        data = f.read()
    offset = 0
    while offset + 2 <= len(data):
        pdu_len = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        if offset + pdu_len > len(data):
            break
        pdus.append(data[offset : offset + pdu_len])
        offset += pdu_len
    return pdus


def load_all_captures(capture_dir):
    """Load PDUs from all capture files in the directory."""
    all_pdus = []
    files = sorted(glob.glob(os.path.join(capture_dir, "*")))
    for fpath in files:
        basename = os.path.basename(fpath)
        if basename.endswith(".hex"):
            all_pdus.extend(read_hex_file(fpath))
        elif basename.endswith(".dat") or basename.endswith(".b64"):
            all_pdus.extend(read_b64_file(fpath))
        elif basename.endswith(".bin"):
            all_pdus.extend(read_bin_file(fpath))
    return all_pdus


# ---- PDU Parsing ----


def bytes_to_addr(b):
    """Convert 6 address bytes (LSO-first) to MSO-first colon-separated hex."""
    return ":".join(f"{x:02X}" for x in reversed(b))


def parse_flags(value):
    return {
        "le_limited_discoverable": bool(value & 0x01),
        "le_general_discoverable": bool(value & 0x02),
        "bredr_not_supported": bool(value & 0x04),
    }


def parse_uuid_16_list(data):
    uuids = []
    for i in range(0, len(data) - 1, 2):
        val = struct.unpack_from("<H", data, i)[0]
        uuids.append(f"{val:04X}")
    return uuids


def parse_uuid_128_list(data):
    uuids = []
    for i in range(0, len(data) - 15, 16):
        raw = data[i : i + 16]
        be = raw[::-1]  # Reverse full byte order from LE to BE
        uid = (
            f"{be[0]:02X}{be[1]:02X}{be[2]:02X}{be[3]:02X}-"
            f"{be[4]:02X}{be[5]:02X}-"
            f"{be[6]:02X}{be[7]:02X}-"
            f"{be[8]:02X}{be[9]:02X}-"
            f"{be[10]:02X}{be[11]:02X}{be[12]:02X}{be[13]:02X}{be[14]:02X}{be[15]:02X}"
        )
        uuids.append(uid)
    return uuids


def parse_ad_structures(ad_data):
    """Parse AD structures and return (structures_list, was_truncated)."""
    structures = []
    offset = 0
    truncated = False

    while offset < len(ad_data):
        length = ad_data[offset]
        if length == 0:
            offset += 1
            continue

        if offset + 1 + length > len(ad_data):
            truncated = True
            break

        ad_type = ad_data[offset + 1]
        ad_content = ad_data[offset + 2 : offset + 1 + length]

        entry = {
            "ad_type": ad_type,
            "ad_type_name": AD_TYPE_NAMES.get(ad_type, f"Unknown (0x{ad_type:02X})"),
            "data_hex": ad_content.hex().upper(),
        }

        if ad_type == 0x01 and len(ad_content) >= 1:
            entry["parsed"] = parse_flags(ad_content[0])
        elif ad_type in (0x02, 0x03):
            entry["parsed"] = {"uuids": parse_uuid_16_list(ad_content)}
        elif ad_type in (0x06, 0x07):
            entry["parsed"] = {"uuids": parse_uuid_128_list(ad_content)}
        elif ad_type in (0x08, 0x09):
            entry["parsed"] = {"name": ad_content.decode("utf-8", errors="replace")}
        elif ad_type == 0x0A and len(ad_content) >= 1:
            entry["parsed"] = {"tx_power_dbm": struct.unpack("b", ad_content[:1])[0]}
        elif ad_type == 0x16 and len(ad_content) >= 2:
            svc = struct.unpack_from("<H", ad_content, 0)[0]
            entry["parsed"] = {
                "service_uuid": f"{svc:04X}",
                "service_data_hex": ad_content[2:].hex().upper(),
            }
        elif ad_type == 0x19 and len(ad_content) >= 2:
            entry["parsed"] = {
                "appearance": struct.unpack_from("<H", ad_content, 0)[0]
            }
        elif ad_type == 0xFF and len(ad_content) >= 2:
            cid = struct.unpack_from("<H", ad_content, 0)[0]
            entry["parsed"] = {
                "company_id": f"{cid:04X}",
                "msd_data_hex": ad_content[2:].hex().upper(),
            }

        structures.append(entry)
        offset += 1 + length

    return structures, truncated


def check_invalid_static_random(adv_a):
    """Check if address is an invalid static random (all 0xFF)."""
    msb = adv_a[5]
    if (msb & 0xC0) == 0xC0 and all(b == 0xFF for b in adv_a):
        return True
    return False


def parse_pdu(raw_bytes, index):
    """Parse a single BLE advertisement channel PDU."""
    if len(raw_bytes) < 2:
        return {
            "index": index,
            "pdu_type": "UNKNOWN",
            "violations": ["pdu_too_short"],
            "ad_structures": [],
        }

    h0 = raw_bytes[0]
    h1 = raw_bytes[1]
    pdu_type = h0 & 0x0F
    tx_add = (h0 >> 6) & 0x01
    payload_len = h1

    result = {
        "index": index,
        "pdu_type": PDU_TYPES.get(pdu_type, f"UNKNOWN_{pdu_type}"),
        "tx_addr_type": "random" if tx_add else "public",
        "payload_length": payload_len,
        "violations": [],
    }

    # Check payload length constraint
    if pdu_type in MAX_PAYLOAD and payload_len > MAX_PAYLOAD[pdu_type]:
        result["violations"].append(
            f"payload_length_exceeds_maximum: {payload_len} > {MAX_PAYLOAD[pdu_type]} for {result['pdu_type']}"
        )

    payload = raw_bytes[2:]

    if pdu_type in (0, 2, 4, 6):
        if len(payload) >= 6:
            adv_a = payload[:6]
            result["advertiser_address"] = bytes_to_addr(adv_a)

            if tx_add == 1 and check_invalid_static_random(adv_a):
                result["violations"].append(
                    "invalid_static_random_address: all bits set to 1"
                )

            end = min(payload_len, len(payload))
            ad_data = payload[6:end]
            ad_structures, truncated = parse_ad_structures(ad_data)
            result["ad_structures"] = ad_structures

            if truncated:
                result["violations"].append(
                    "ad_structure_truncated: AD length exceeds remaining data"
                )

            for ad in ad_structures:
                if ad.get("ad_type") == 0x01 and "parsed" in ad:
                    flags = ad["parsed"]
                    if flags.get("le_limited_discoverable") and flags.get(
                        "le_general_discoverable"
                    ):
                        result["violations"].append(
                            "flags_conflict: both LE Limited and LE General Discoverable set"
                        )

    elif pdu_type == 1:
        if len(payload) >= 12:
            result["advertiser_address"] = bytes_to_addr(payload[:6])
            result["target_address"] = bytes_to_addr(payload[6:12])
            adv_a = payload[:6]
            if tx_add == 1 and check_invalid_static_random(adv_a):
                result["violations"].append(
                    "invalid_static_random_address: all bits set to 1"
                )
        result["ad_structures"] = []

    elif pdu_type == 3:
        if len(payload) >= 12:
            result["advertiser_address"] = bytes_to_addr(payload[6:12])
        result["ad_structures"] = []

    else:
        if len(payload) >= 6:
            result["advertiser_address"] = bytes_to_addr(payload[:6])
        result["ad_structures"] = []

    return result


# ---- Main ----


def main():
    capture_dir = "/app/captures"
    output_file = "/app/diagnostic_report.json"

    raw_pdus = load_all_captures(capture_dir)
    pdus = [parse_pdu(raw, i) for i, raw in enumerate(raw_pdus)]

    # Compute summary statistics
    type_counts = {}
    unique_addrs = set()
    nordic_count = 0

    for p in pdus:
        ptype = p.get("pdu_type", "UNKNOWN")
        type_counts[ptype] = type_counts.get(ptype, 0) + 1

        addr = p.get("advertiser_address")
        if addr:
            unique_addrs.add(addr)

        for ad in p.get("ad_structures", []):
            if ad.get("ad_type") == 0xFF and "parsed" in ad:
                if ad["parsed"].get("company_id") == "0059":
                    nordic_count += 1
                    break

    invalid_count = sum(1 for p in pdus if p.get("violations"))
    total_violations = sum(len(p.get("violations", [])) for p in pdus)

    report = {
        "pdus": pdus,
        "summary": {
            "total_pdus": len(pdus),
            "valid_pdus": len(pdus) - invalid_count,
            "invalid_pdus": invalid_count,
            "pdu_type_counts": type_counts,
            "unique_advertisers": len(unique_addrs),
            "nordic_msd_count": nordic_count,
            "total_violations": total_violations,
        },
    }

    with open(output_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Diagnostic report written to {output_file}")
    print(
        f"Total: {len(pdus)} PDUs, {len(pdus)-invalid_count} valid, "
        f"{invalid_count} invalid, {total_violations} violations"
    )


if __name__ == "__main__":
    main()
