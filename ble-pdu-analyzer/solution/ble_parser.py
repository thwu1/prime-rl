#!/usr/bin/env python3
"""BLE Advertisement PDU Parser and Analyzer.

Parses raw BLE Link Layer advertisement channel PDUs per Bluetooth Core
Specification v5.4 and produces a structured JSON analysis report.
"""
import json
import struct

PDU_TYPES = {
    0: "ADV_IND",
    1: "ADV_DIRECT_IND",
    2: "ADV_NONCONN_IND",
    3: "SCAN_REQ",
    4: "SCAN_RSP",
    5: "CONNECT_IND",
    6: "ADV_SCAN_IND",
    7: "ADV_EXT_IND",
}

MAX_PAYLOAD = {
    0: 37,
    1: 12,
    2: 37,
    4: 37,
    6: 37,
}

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


def bytes_to_addr(b):
    """Convert 6 address bytes (LSO-first in PDU) to MSO-first colon-separated hex."""
    return ":".join(f"{x:02X}" for x in reversed(b))


def parse_flags(value):
    return {
        "le_limited_discoverable": bool(value & 0x01),
        "le_general_discoverable": bool(value & 0x02),
        "bredr_not_supported": bool(value & 0x04),
        "le_bredr_controller": bool(value & 0x08),
        "le_bredr_host": bool(value & 0x10),
    }


def parse_uuid_16_list(data):
    uuids = []
    for i in range(0, len(data) - 1, 2):
        uuid_val = struct.unpack_from("<H", data, i)[0]
        uuids.append(f"{uuid_val:04X}")
    return uuids


def parse_uuid_128_list(data):
    uuids = []
    for i in range(0, len(data) - 15, 16):
        uuid_bytes = data[i:i + 16]
        be = uuid_bytes[::-1]
        uuid_str = (
            f"{be[0]:02X}{be[1]:02X}{be[2]:02X}{be[3]:02X}-"
            f"{be[4]:02X}{be[5]:02X}-"
            f"{be[6]:02X}{be[7]:02X}-"
            f"{be[8]:02X}{be[9]:02X}-"
            f"{be[10]:02X}{be[11]:02X}{be[12]:02X}{be[13]:02X}{be[14]:02X}{be[15]:02X}"
        )
        uuids.append(uuid_str)
    return uuids


def parse_ad_structures(ad_data):
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
            ad_type = ad_data[offset + 1] if offset + 1 < len(ad_data) else None
            structures.append({
                "offset": offset,
                "length": length,
                "ad_type": ad_type,
                "ad_type_name": AD_TYPE_NAMES.get(ad_type, "Unknown") if ad_type is not None else "Unknown",
                "truncated": True,
                "data_hex": ad_data[offset + 2:].hex().upper() if offset + 2 < len(ad_data) else "",
            })
            break

        ad_type = ad_data[offset + 1]
        ad_content = ad_data[offset + 2:offset + 1 + length]

        structure = {
            "offset": offset,
            "length": length,
            "ad_type": ad_type,
            "ad_type_name": AD_TYPE_NAMES.get(ad_type, f"Unknown (0x{ad_type:02X})"),
            "data_hex": ad_content.hex().upper(),
        }

        if ad_type == 0x01:
            if len(ad_content) >= 1:
                structure["parsed"] = parse_flags(ad_content[0])
        elif ad_type in (0x02, 0x03):
            structure["parsed"] = {"uuids": parse_uuid_16_list(ad_content)}
        elif ad_type in (0x06, 0x07):
            structure["parsed"] = {"uuids": parse_uuid_128_list(ad_content)}
        elif ad_type in (0x08, 0x09):
            try:
                structure["parsed"] = {"name": ad_content.decode("utf-8")}
            except UnicodeDecodeError:
                structure["parsed"] = {"name": ad_content.decode("utf-8", errors="replace")}
        elif ad_type == 0x0A:
            if len(ad_content) >= 1:
                tx_power = struct.unpack("b", ad_content[:1])[0]
                structure["parsed"] = {"tx_power_dbm": tx_power}
        elif ad_type == 0x16:
            if len(ad_content) >= 2:
                uuid_val = struct.unpack_from("<H", ad_content, 0)[0]
                structure["parsed"] = {
                    "service_uuid": f"{uuid_val:04X}",
                    "service_data_hex": ad_content[2:].hex().upper(),
                }
        elif ad_type == 0x19:
            if len(ad_content) >= 2:
                appearance = struct.unpack_from("<H", ad_content, 0)[0]
                structure["parsed"] = {"appearance": appearance}
        elif ad_type == 0xFF:
            if len(ad_content) >= 2:
                company_id = struct.unpack_from("<H", ad_content, 0)[0]
                structure["parsed"] = {
                    "company_id": f"{company_id:04X}",
                    "msd_data_hex": ad_content[2:].hex().upper(),
                }

        structures.append(structure)
        offset += 1 + length

    return structures, truncated


def check_static_random_address(adv_a):
    """Check if a random address is an invalid static random (all 0xFF)."""
    msb = adv_a[5]
    if (msb & 0xC0) == 0xC0:
        if all(b == 0xFF for b in adv_a):
            return True
    return False


def parse_pdu(hex_string, index):
    raw_bytes = bytes.fromhex(hex_string.strip())

    if len(raw_bytes) < 2:
        return {
            "index": index,
            "pdu_type": "UNKNOWN",
            "violations": ["pdu_too_short"],
            "ad_structures": [],
        }

    header_byte0 = raw_bytes[0]
    header_byte1 = raw_bytes[1]

    pdu_type_code = header_byte0 & 0x0F
    tx_add = (header_byte0 >> 6) & 0x01
    rx_add = (header_byte0 >> 7) & 0x01
    payload_length = header_byte1

    pdu_type_name = PDU_TYPES.get(pdu_type_code, f"UNKNOWN_{pdu_type_code}")

    result = {
        "index": index,
        "raw_hex": hex_string.strip().upper(),
        "pdu_type": pdu_type_name,
        "pdu_type_code": pdu_type_code,
        "tx_addr_type": "random" if tx_add else "public",
        "rx_addr_type": "random" if rx_add else "public",
        "payload_length": payload_length,
        "violations": [],
    }

    if pdu_type_code in MAX_PAYLOAD:
        if payload_length > MAX_PAYLOAD[pdu_type_code]:
            result["violations"].append(
                f"payload_length_exceeds_maximum: {payload_length} > "
                f"{MAX_PAYLOAD[pdu_type_code]} for {pdu_type_name}"
            )

    payload = raw_bytes[2:]

    if pdu_type_code in (0, 2, 4, 6):
        if len(payload) >= 6:
            adv_a = payload[:6]
            result["advertiser_address"] = bytes_to_addr(adv_a)

            if tx_add == 1 and check_static_random_address(adv_a):
                result["violations"].append(
                    "invalid_static_random_address: all bits set to 1"
                )

            end = min(payload_length, len(payload))
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
                    if flags.get("le_limited_discoverable") and flags.get("le_general_discoverable"):
                        result["violations"].append(
                            "flags_conflict: both LE Limited and LE General Discoverable set"
                        )

    elif pdu_type_code == 1:
        if len(payload) >= 12:
            adv_a = payload[:6]
            target_a = payload[6:12]
            result["advertiser_address"] = bytes_to_addr(adv_a)
            result["target_address"] = bytes_to_addr(target_a)

            if tx_add == 1 and check_static_random_address(adv_a):
                result["violations"].append(
                    "invalid_static_random_address: all bits set to 1"
                )
        result["ad_structures"] = []

    elif pdu_type_code == 3:
        if len(payload) >= 12:
            scan_a = payload[:6]
            adv_a = payload[6:12]
            result["scanner_address"] = bytes_to_addr(scan_a)
            result["advertiser_address"] = bytes_to_addr(adv_a)
        result["ad_structures"] = []

    else:
        if len(payload) >= 6:
            result["advertiser_address"] = bytes_to_addr(payload[:6])
        result["ad_structures"] = []

    return result


def main():
    capture_file = "/app/captures/ble_capture.hex"
    output_file = "/app/analysis_report.json"

    with open(capture_file) as f:
        lines = [line.strip() for line in f if line.strip()]

    pdus = [parse_pdu(line, i) for i, line in enumerate(lines)]

    type_counts = {}
    unique_addrs = set()
    nordic_count = 0

    for p in pdus:
        pdu_type = p.get("pdu_type", "UNKNOWN")
        type_counts[pdu_type] = type_counts.get(pdu_type, 0) + 1

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

    print(f"Analysis complete. Report written to {output_file}")
    print(f"Total PDUs: {len(pdus)}, Valid: {len(pdus) - invalid_count}, "
          f"Violations: {total_violations}")


if __name__ == "__main__":
    main()
