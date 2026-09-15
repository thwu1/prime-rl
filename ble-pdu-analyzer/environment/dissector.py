#!/usr/bin/env python3
"""BLE Link Layer PDU Dissector Tool

Decodes BLE advertisement channel PDUs from a hex-encoded capture file.
Each line of the input file should contain one hex-encoded PDU
(raw bytes starting from the 2-byte PDU header).

Usage: python3 dissector.py <hex_capture_file>
"""
import json
import struct
import sys

PDU_TYPE_NAMES = {
    0: "ADV_IND",
    1: "ADV_DIRECT_IND",
    2: "ADV_NONCONN_IND",
    3: "SCAN_REQ",
    4: "SCAN_RSP",
    5: "CONNECT_IND",
    6: "ADV_SCAN_IND",
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

MAX_PAYLOAD_LEN = {0: 37, 1: 12, 2: 37, 4: 37, 6: 37}


def addr_to_str(addr_bytes):
    """Convert 6 address bytes (stored LSO-first in PDU) to colon-separated hex."""
    return ":".join(f"{b:02X}" for b in reversed(addr_bytes))


def parse_flags(val):
    return {
        "le_limited_discoverable": bool(val & 0x01),
        "le_general_discoverable": bool(val & 0x02),
        "bredr_not_supported": bool(val & 0x04),
    }


def parse_ad_structures(ad_data):
    """Parse AD structures from advertisement data payload."""
    structures = []
    pos = 0
    truncated = False

    while pos < len(ad_data):
        length = ad_data[pos]
        if length == 0:
            pos += 1
            continue

        if pos + 1 + length > len(ad_data):
            truncated = True
            break

        ad_type = ad_data[pos + 1]
        content = ad_data[pos + 2 : pos + 1 + length]

        entry = {
            "ad_type": ad_type,
            "ad_type_name": AD_TYPE_NAMES.get(ad_type, f"Unknown (0x{ad_type:02X})"),
            "data_hex": content.hex().upper(),
        }

        if ad_type == 0x01 and len(content) >= 1:
            entry["parsed"] = parse_flags(content[0])

        elif ad_type in (0x08, 0x09):
            entry["parsed"] = {"name": content.decode("utf-8", errors="replace")}

        elif ad_type in (0x02, 0x03):
            uuids = []
            for i in range(0, len(content) - 1, 2):
                uuids.append(f"{struct.unpack_from('<H', content, i)[0]:04X}")
            entry["parsed"] = {"uuids": uuids}

        elif ad_type in (0x06, 0x07):
            uuids = []
            for i in range(0, len(content) - 15, 16):
                # Format 128-bit UUID from raw LE bytes
                b = content[i : i + 16]
                uid = (
                    f"{b[0]:02X}{b[1]:02X}{b[2]:02X}{b[3]:02X}-"
                    f"{b[4]:02X}{b[5]:02X}-"
                    f"{b[6]:02X}{b[7]:02X}-"
                    f"{b[8]:02X}{b[9]:02X}-"
                    f"{b[10]:02X}{b[11]:02X}{b[12]:02X}{b[13]:02X}{b[14]:02X}{b[15]:02X}"
                )
                uuids.append(uid)
            entry["parsed"] = {"uuids": uuids}

        elif ad_type == 0x0A and len(content) >= 1:
            entry["parsed"] = {"tx_power_dbm": struct.unpack("b", content[:1])[0]}

        elif ad_type == 0xFF and len(content) >= 2:
            cid = struct.unpack(">H", content[:2])[0]
            entry["parsed"] = {
                "company_id": f"{cid:04X}",
                "msd_data_hex": content[2:].hex().upper(),
            }

        elif ad_type == 0x16 and len(content) >= 2:
            svc = struct.unpack_from("<H", content, 0)[0]
            entry["parsed"] = {
                "service_uuid": f"{svc:04X}",
                "service_data_hex": content[2:].hex().upper(),
            }

        elif ad_type == 0x19 and len(content) >= 2:
            entry["parsed"] = {"appearance": struct.unpack_from("<H", content, 0)[0]}

        structures.append(entry)
        pos += 1 + length

    return structures, truncated


def dissect_pdu(hex_str):
    """Dissect a single BLE Link Layer PDU from hex string."""
    raw = bytes.fromhex(hex_str.strip())
    if len(raw) < 2:
        return {"error": "PDU too short"}

    h0, h1 = raw[0], raw[1]
    pdu_type = h0 & 0x0F
    tx_add = (h0 >> 5) & 1  # TxAdd address type indicator
    payload_len = h1
    payload = raw[2:]

    result = {
        "pdu_type": PDU_TYPE_NAMES.get(pdu_type, f"RESERVED_{pdu_type}"),
        "tx_addr_type": "random" if tx_add else "public",
        "payload_length": payload_len,
        "violations": [],
    }

    # Check payload length constraints
    if pdu_type in MAX_PAYLOAD_LEN and payload_len > MAX_PAYLOAD_LEN[pdu_type]:
        result["violations"].append(
            f"payload_length_exceeds_maximum: {payload_len} > {MAX_PAYLOAD_LEN[pdu_type]}"
        )

    # Parse based on PDU type
    if pdu_type in (0, 2, 4, 6):
        if len(payload) >= 6:
            adv_a = payload[:6]
            result["advertiser_address"] = addr_to_str(adv_a)

            # Check for invalid static random address
            if tx_add == 1 and (adv_a[5] & 0xC0) == 0xC0:
                if all(b == 0xFF for b in adv_a):
                    result["violations"].append("invalid_static_random_address")

            end = min(payload_len, len(payload))
            ad_data = payload[6:end]
            ads, trunc = parse_ad_structures(ad_data)
            result["ad_structures"] = ads

            if trunc:
                result["violations"].append("ad_structure_truncated")

            # Check flag conflicts
            for ad in ads:
                if ad.get("ad_type") == 0x01 and "parsed" in ad:
                    f = ad["parsed"]
                    if f.get("le_limited_discoverable") and f.get("le_general_discoverable"):
                        result["violations"].append("flags_conflict_limited_and_general")

    elif pdu_type == 1:
        if len(payload) >= 12:
            result["advertiser_address"] = addr_to_str(payload[:6])
            result["target_address"] = addr_to_str(payload[6:12])
        result["ad_structures"] = []

    elif pdu_type == 3:
        if len(payload) >= 12:
            result["advertiser_address"] = addr_to_str(payload[6:12])
        result["ad_structures"] = []

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: dissector.py <hex_capture_file>")
        print("Each line should contain one hex-encoded BLE PDU.")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        lines = [l.strip() for l in f if l.strip()]

    results = []
    for i, line in enumerate(lines):
        pdu = dissect_pdu(line)
        pdu["index"] = i
        results.append(pdu)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
