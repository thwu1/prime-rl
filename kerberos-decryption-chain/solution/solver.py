#!/usr/bin/env python3
"""Solve the Kerberos incident forensics challenge.


Parses keytab files, decrypts captured Kerberos tickets via trial
decryption, identifies anomalous (forged) tickets, and writes a
forensic report.
"""

import json
import os
import struct
from datetime import datetime

from scapy.libs.rfc3961 import Key, EncryptionType


# ================================================================
# MIT keytab parser
# ================================================================

def parse_keytab(filepath):
    """Parse MIT keytab file (format version 0x0502)."""
    with open(filepath, "rb") as f:
        data = f.read()

    version = struct.unpack(">H", data[:2])[0]
    assert version == 0x0502, f"Unexpected keytab version: {version:#x}"

    entries = []
    offset = 2
    while offset < len(data):
        if offset + 4 > len(data):
            break
        entry_size = struct.unpack(">i", data[offset : offset + 4])[0]
        if entry_size <= 0:
            # Deleted entry (hole) — skip
            offset += 4 + abs(entry_size)
            continue
        entry_data = data[offset + 4 : offset + 4 + entry_size]
        offset += 4 + entry_size

        pos = 0
        num_components = struct.unpack(">H", entry_data[pos : pos + 2])[0]
        pos += 2

        realm_len = struct.unpack(">H", entry_data[pos : pos + 2])[0]
        pos += 2
        realm = entry_data[pos : pos + realm_len].decode()
        pos += realm_len

        components = []
        for _ in range(num_components):
            comp_len = struct.unpack(">H", entry_data[pos : pos + 2])[0]
            pos += 2
            components.append(entry_data[pos : pos + comp_len].decode())
            pos += comp_len

        name_type = struct.unpack(">I", entry_data[pos : pos + 4])[0]
        pos += 4
        timestamp = struct.unpack(">I", entry_data[pos : pos + 4])[0]
        pos += 4
        vno8 = entry_data[pos]
        pos += 1

        keytype = struct.unpack(">H", entry_data[pos : pos + 2])[0]
        pos += 2
        keylen = struct.unpack(">H", entry_data[pos : pos + 2])[0]
        pos += 2
        keyvalue = entry_data[pos : pos + keylen]
        pos += keylen

        # Optional 32-bit kvno
        kvno = vno8
        if pos + 4 <= len(entry_data):
            kvno = struct.unpack(">I", entry_data[pos : pos + 4])[0]

        principal = "/".join(components) + "@" + realm
        try:
            key = Key(EncryptionType(keytype), key=keyvalue)
        except Exception:
            key = None

        entries.append(
            {
                "principal": principal,
                "etype": keytype,
                "kvno": kvno,
                "key": key,
            }
        )

    return entries


# ================================================================
# ASN.1 DER parser (minimal, for Kerberos structures)
# ================================================================

def parse_der_tlv(data, offset=0):
    """Parse one DER TLV at the given offset. Returns (tag, value, next_offset)."""
    tag = data[offset]
    offset += 1

    length = data[offset]
    offset += 1
    if length & 0x80:
        num_bytes = length & 0x7F
        length = int.from_bytes(data[offset : offset + num_bytes], "big")
        offset += num_bytes

    value = data[offset : offset + length]
    return tag, value, offset + length


def parse_der_sequence_items(data):
    """Parse all TLVs from a SEQUENCE/SET value."""
    items = []
    offset = 0
    while offset < len(data):
        tag, value, offset = parse_der_tlv(data, offset)
        items.append((tag, value))
    return items


def parse_der_integer(data):
    """Parse DER INTEGER value bytes to int."""
    return int.from_bytes(data, "big", signed=True if data[0] & 0x80 else False)


def parse_context_field(items, ctx_num):
    """Extract the inner TLV from a context-tagged field."""
    for tag, value in items:
        if tag == (0xA0 | ctx_num):
            return value
    return None


def parse_inner_tlv(ctx_value):
    """Parse the single TLV inside a context-tagged field."""
    tag, value, _ = parse_der_tlv(ctx_value)
    return tag, value


def parse_general_string(ctx_value):
    """Extract GeneralString from context field value."""
    _, value = parse_inner_tlv(ctx_value)
    return value.decode()


def parse_integer(ctx_value):
    """Extract INTEGER from context field value."""
    _, value = parse_inner_tlv(ctx_value)
    return parse_der_integer(value)


def parse_octet_string(ctx_value):
    """Extract OCTET STRING from context field value."""
    _, value = parse_inner_tlv(ctx_value)
    return value


def parse_generalized_time(ctx_value):
    """Extract GeneralizedTime from context field value."""
    _, value = parse_inner_tlv(ctx_value)
    return value.decode()


def parse_principal_name(ctx_value):
    """Parse PrincipalName SEQUENCE from context field."""
    seq_items = parse_der_sequence_items(ctx_value)
    # [0] = nameType, [1] = SEQUENCE OF GeneralString
    name_strs_val = parse_context_field(seq_items, 1)

    # name_strs_val wraps a SEQUENCE OF GeneralString TLV
    inner_items = parse_der_sequence_items(name_strs_val)
    if inner_items and inner_items[0][0] == 0x30:
        # Unwrap the SEQUENCE OF wrapper
        gs_items = parse_der_sequence_items(inner_items[0][1])
    else:
        gs_items = inner_items
    components = [v.decode() for _, v in gs_items]
    return components


def parse_encryption_key(ctx_value):
    """Parse EncryptionKey SEQUENCE from context field."""
    seq_items = parse_der_sequence_items(ctx_value)
    etype_val = parse_context_field(seq_items, 0)
    keyval = parse_context_field(seq_items, 1)
    etype = parse_integer(etype_val) if etype_val else 0
    key_bytes = parse_octet_string(keyval) if keyval else b""
    return etype, key_bytes


# ================================================================
# KRB_Ticket and EncTicketPart parsers
# ================================================================

def parse_krb_ticket(data):
    """Parse a DER-encoded KRB_Ticket (APPLICATION 1)."""
    tag, inner, _ = parse_der_tlv(data)
    assert tag == 0x61, f"Expected APPLICATION 1 (0x61), got {tag:#x}"

    items = parse_der_sequence_items(inner)

    tkt_vno = parse_integer(parse_context_field(items, 0))
    realm = parse_general_string(parse_context_field(items, 1))

    # sname [2]: PrincipalName inside context
    sname_ctx = parse_context_field(items, 2)
    sname_seq_items = parse_der_sequence_items(sname_ctx)
    # PrincipalName is a SEQUENCE, parse its inner SEQUENCE
    if sname_seq_items and sname_seq_items[0][0] == 0x30:
        sname_comps = parse_principal_name(sname_seq_items[0][1])
    else:
        sname_comps = parse_principal_name(sname_ctx)

    # enc-part [3]: EncryptedData
    enc_ctx = parse_context_field(items, 3)
    enc_items_raw = parse_der_sequence_items(enc_ctx)
    # EncryptedData is a SEQUENCE
    if enc_items_raw and enc_items_raw[0][0] == 0x30:
        enc_items = parse_der_sequence_items(enc_items_raw[0][1])
    else:
        enc_items = enc_items_raw

    etype = parse_integer(parse_context_field(enc_items, 0))
    kvno_field = parse_context_field(enc_items, 1)
    kvno = parse_integer(kvno_field) if kvno_field else None
    cipher = parse_octet_string(parse_context_field(enc_items, 2))

    return {
        "tkt_vno": tkt_vno,
        "realm": realm,
        "sname": "/".join(sname_comps),
        "etype": etype,
        "kvno": kvno,
        "cipher": cipher,
    }


def parse_enc_ticket_part(data):
    """Parse DER-encoded EncTicketPart (APPLICATION 3)."""
    tag, inner, _ = parse_der_tlv(data)
    assert tag == 0x63, f"Expected APPLICATION 3 (0x63), got {tag:#x}"

    items = parse_der_sequence_items(inner)

    # [1] key: EncryptionKey
    key_ctx = parse_context_field(items, 1)
    key_inner = parse_der_sequence_items(key_ctx)
    if key_inner and key_inner[0][0] == 0x30:
        sk_etype, sk_bytes = parse_encryption_key(key_inner[0][1])
    else:
        sk_etype, sk_bytes = parse_encryption_key(key_ctx)

    # [2] crealm
    crealm = parse_general_string(parse_context_field(items, 2))

    # [3] cname: PrincipalName
    cname_ctx = parse_context_field(items, 3)
    cname_inner = parse_der_sequence_items(cname_ctx)
    if cname_inner and cname_inner[0][0] == 0x30:
        cname_comps = parse_principal_name(cname_inner[0][1])
    else:
        cname_comps = parse_principal_name(cname_ctx)

    # [5] authtime
    authtime = parse_generalized_time(parse_context_field(items, 5))

    # [7] endtime
    endtime = parse_generalized_time(parse_context_field(items, 7))

    return {
        "session_key_etype": sk_etype,
        "session_key_hex": sk_bytes.hex(),
        "crealm": crealm,
        "cname": "/".join(cname_comps),
        "authtime": authtime,
        "endtime": endtime,
    }


# ================================================================
# Main solver
# ================================================================

def main():
    # ---- Load manifest ----
    with open("/app/incident/manifest.json") as f:
        manifest = json.load(f)
    known_users = set(manifest.get("known_users", []))

    # ---- Parse all keytab files ----
    keytab_dir = "/app/incident/keytabs"
    keytab_files = sorted(os.listdir(keytab_dir))

    all_keys = {}  # keytab_name -> list of entries
    keytab_summary = {}

    for kt_file in keytab_files:
        entries = parse_keytab(os.path.join(keytab_dir, kt_file))
        all_keys[kt_file] = entries
        keytab_summary[kt_file] = [
            {"principal": e["principal"], "etype": e["etype"], "kvno": e["kvno"]}
            for e in entries
        ]
        print(f"Keytab {kt_file}: {len(entries)} entries")
        for e in entries:
            print(f"  {e['principal']} etype={e['etype']} kvno={e['kvno']}")

    # ---- Decrypt all tickets ----
    ticket_dir = "/app/incident/tickets"
    ticket_files = sorted(os.listdir(ticket_dir))

    ticket_decryptions = {}

    for tkt_file in ticket_files:
        with open(os.path.join(ticket_dir, tkt_file), "rb") as f:
            tkt_data = f.read()

        tkt = parse_krb_ticket(tkt_data)
        print(f"\nTicket {tkt_file}: sname={tkt['sname']}, etype={tkt['etype']}, kvno={tkt['kvno']}")

        # Trial decryption: try matching keys first, then all keys
        decrypted = None
        used_keytab = None

        for keytab_name, entries in all_keys.items():
            for entry in entries:
                if entry["key"] is None:
                    continue
                # Match by etype and kvno
                if entry["etype"] != tkt["etype"]:
                    continue
                if tkt["kvno"] is not None and entry["kvno"] != tkt["kvno"]:
                    continue
                try:
                    plaintext = entry["key"].decrypt(2, tkt["cipher"])
                    enc_tkt = parse_enc_ticket_part(plaintext)
                    decrypted = enc_tkt
                    used_keytab = keytab_name
                    break
                except Exception:
                    continue
            if decrypted:
                break

        # Fallback: try all keys regardless of etype/kvno
        if not decrypted:
            for keytab_name, entries in all_keys.items():
                for entry in entries:
                    if entry["key"] is None:
                        continue
                    try:
                        plaintext = entry["key"].decrypt(2, tkt["cipher"])
                        enc_tkt = parse_enc_ticket_part(plaintext)
                        decrypted = enc_tkt
                        used_keytab = keytab_name
                        break
                    except Exception:
                        continue
                if decrypted:
                    break

        if not decrypted:
            print(f"  FAILED to decrypt {tkt_file}")
            continue

        ticket_decryptions[tkt_file] = {
            "service_principal": tkt["sname"],
            "client_principal": decrypted["cname"],
            "client_realm": decrypted["crealm"],
            "encryption_type": tkt["etype"],
            "auth_time": decrypted["authtime"],
            "end_time": decrypted["endtime"],
            "decrypted_with_keytab": used_keytab,
            "session_key_hex": decrypted["session_key_hex"],
        }
        print(f"  Decrypted: client={decrypted['cname']}, keytab={used_keytab}")

    # ---- Identify anomalous tickets ----
    anomalous = []
    attacker_principals = set()

    for tkt_file, details in ticket_decryptions.items():
        auth_dt = datetime.strptime(details["auth_time"], "%Y%m%d%H%M%SZ")
        end_dt = datetime.strptime(details["end_time"], "%Y%m%d%H%M%SZ")
        lifetime_hours = (end_dt - auth_dt).total_seconds() / 3600.0

        client = details["client_principal"]

        # Golden ticket indicators:
        # 1. Extremely long ticket lifetime (normal TGT ~ 10 hours)
        # 2. Client principal not in known user list
        is_anomalous = False
        reasons = []
        if lifetime_hours > 168:  # > 1 week
            is_anomalous = True
            reasons.append(f"lifetime={lifetime_hours:.0f}h")
        if client not in known_users:
            is_anomalous = True
            reasons.append(f"unknown_client={client}")

        if is_anomalous:
            anomalous.append(tkt_file)
            attacker_principals.add(client)
            print(f"  ANOMALOUS: {tkt_file} ({', '.join(reasons)})")

    anomalous.sort()

    # ---- Determine compromised keytab ----
    compromised_keytabs = set()
    for tkt_file in anomalous:
        compromised_keytabs.add(ticket_decryptions[tkt_file]["decrypted_with_keytab"])

    compromised_keytab = sorted(compromised_keytabs)[0] if compromised_keytabs else ""
    attacker_principal = sorted(attacker_principals)[0] if attacker_principals else ""

    # ---- Write report ----
    report = {
        "keytab_summary": keytab_summary,
        "ticket_decryptions": ticket_decryptions,
        "anomalous_tickets": anomalous,
        "compromised_keytab": compromised_keytab,
        "attacker_principal": attacker_principal,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to /app/report.json")
    print(f"Anomalous tickets: {anomalous}")
    print(f"Compromised keytab: {compromised_keytab}")
    print(f"Attacker principal: {attacker_principal}")


if __name__ == "__main__":
    main()
