#!/usr/bin/env python3
"""Generate Kerberos incident forensics challenge data.

Builds keytab files, DER-encoded KRB_Ticket structures, a manifest,
and verification hashes for the forensics challenge.
"""

import json
import os
import struct
import hashlib

from scapy.libs.rfc3961 import Key, EncryptionType

AES256 = EncryptionType.AES256_CTS_HMAC_SHA1_96  # etype 18
AES128 = EncryptionType.AES128_CTS_HMAC_SHA1_96  # etype 17

# ---- Deterministic session keys for each ticket ----
SESSION_KEYS = [
    bytes.fromhex(
        "a0b1c2d3e4f5061728394a5b6c7d8e9f"
        "a0b1c2d3e4f5061728394a5b6c7d8e9f"
    ),
    bytes.fromhex(
        "1122334455667788990011223344556677"
        "889900112233445566778899001122"
    ),
    bytes.fromhex(
        "deadbeefcafebabe0102030405060708"
        "deadbeefcafebabe0102030405060708"
    ),
    bytes.fromhex(
        "f0e1d2c3b4a596870f1e2d3c4b5a6978"
        "f0e1d2c3b4a596870f1e2d3c4b5a6978"
    ),
    bytes.fromhex(
        "aabbccddee001122334455667788990011"
        "223344556677889900aabbccddeeff"
    ),
    bytes.fromhex(
        "0123456789abcdef0123456789abcdef"
        "0123456789abcdef0123456789abcdef"
    ),
]

# ================================================================
# DER encoding helpers (pure Python, no ASN.1 library dependency)
# ================================================================

def _der_len(length):
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return bytes([0x81, length])
    elif length < 0x10000:
        return bytes([0x82, length >> 8, length & 0xFF])
    else:
        return bytes([0x83, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF])


def _der_tlv(tag_byte, value):
    return bytes([tag_byte]) + _der_len(len(value)) + value


def der_integer(val):
    if val == 0:
        return _der_tlv(0x02, b'\x00')
    n = val
    result = []
    while n > 0:
        result.append(n & 0xFF)
        n >>= 8
    result.reverse()
    if result[0] & 0x80:
        result.insert(0, 0)
    return _der_tlv(0x02, bytes(result))


def der_octet_string(val):
    return _der_tlv(0x04, val)


def der_general_string(val):
    if isinstance(val, str):
        val = val.encode()
    return _der_tlv(0x1B, val)


def der_generalized_time(val):
    if isinstance(val, str):
        val = val.encode()
    return _der_tlv(0x18, val)


def der_bit_string(val_bytes, unused=0):
    return _der_tlv(0x03, bytes([unused]) + val_bytes)


def der_sequence(items):
    return _der_tlv(0x30, b''.join(items))


def der_context(num, inner):
    """Explicit context tag (constructed)."""
    return _der_tlv(0xA0 | num, inner)


def der_application(num, inner):
    """Application tag (constructed, implicit replaces SEQUENCE)."""
    return _der_tlv(0x60 | num, inner)


# ================================================================
# Kerberos structure builders
# ================================================================

def build_encryption_key(etype, key_bytes):
    """EncryptionKey ::= SEQUENCE { [0] keytype, [1] keyvalue }"""
    return der_sequence([
        der_context(0, der_integer(etype)),
        der_context(1, der_octet_string(key_bytes)),
    ])


def build_principal_name(name_type, components):
    """PrincipalName ::= SEQUENCE { [0] nameType, [1] SEQUENCE OF GeneralString }"""
    gs_list = [der_general_string(c) for c in components]
    return der_sequence([
        der_context(0, der_integer(name_type)),
        der_context(1, der_sequence(gs_list)),
    ])


def build_transited_encoding():
    """TransitedEncoding ::= SEQUENCE { [0] trType, [1] contents }"""
    return der_sequence([
        der_context(0, der_integer(0)),
        der_context(1, der_octet_string(b"")),
    ])


def build_enc_ticket_part(flags_bytes, session_key_bytes, sk_etype,
                           crealm, cname, authtime, endtime):
    """EncTicketPart ::= [APPLICATION 3] SEQUENCE { ... }"""
    fields = b''
    fields += der_context(0, der_bit_string(flags_bytes, 0))
    fields += der_context(1, build_encryption_key(sk_etype, session_key_bytes))
    fields += der_context(2, der_general_string(crealm))
    fields += der_context(3, build_principal_name(1, [cname]))  # NT-PRINCIPAL
    fields += der_context(4, build_transited_encoding())
    fields += der_context(5, der_generalized_time(authtime))
    # [6] starttime OPTIONAL — omitted
    fields += der_context(7, der_generalized_time(endtime))
    # [8] renew-till, [9] caddr, [10] authorization-data — all OPTIONAL, omitted
    return der_application(3, fields)


def build_encrypted_data(etype, kvno, cipher_bytes):
    """EncryptedData ::= SEQUENCE { [0] etype, [1] kvno, [2] cipher }"""
    return der_sequence([
        der_context(0, der_integer(etype)),
        der_context(1, der_integer(kvno)),
        der_context(2, der_octet_string(cipher_bytes)),
    ])


def build_krb_ticket(realm, sname_components, etype, kvno, cipher_bytes):
    """Ticket ::= [APPLICATION 1] SEQUENCE { ... }"""
    fields = b''
    fields += der_context(0, der_integer(5))  # tkt-vno = 5
    fields += der_context(1, der_general_string(realm))
    fields += der_context(2, build_principal_name(2, sname_components))  # NT-SRV-INST
    fields += der_context(3, build_encrypted_data(etype, kvno, cipher_bytes))
    return der_application(1, fields)


# ================================================================
# MIT keytab builder
# ================================================================

def build_keytab_entry(components, realm, name_type, kvno, etype, key_bytes,
                        ts=1710460800):
    entry = bytearray()
    entry.extend(struct.pack(">H", len(components)))
    realm_b = realm.encode()
    entry.extend(struct.pack(">H", len(realm_b)))
    entry.extend(realm_b)
    for comp in components:
        comp_b = comp.encode()
        entry.extend(struct.pack(">H", len(comp_b)))
        entry.extend(comp_b)
    entry.extend(struct.pack(">I", name_type))
    entry.extend(struct.pack(">I", ts))
    entry.extend(struct.pack("B", kvno & 0xFF))
    entry.extend(struct.pack(">HH", etype, len(key_bytes)))
    entry.extend(key_bytes)
    entry.extend(struct.pack(">I", kvno))
    return bytes(entry)


def build_keytab(entries):
    buf = bytearray(struct.pack(">H", 0x0502))
    for args in entries:
        entry = build_keytab_entry(*args)
        buf.extend(struct.pack(">i", len(entry)))
        buf.extend(entry)
    return bytes(buf)


# ================================================================
# Main
# ================================================================

def main():
    os.makedirs("/app/incident/keytabs", exist_ok=True)
    os.makedirs("/app/incident/tickets", exist_ok=True)
    os.makedirs("/var/lib/task_verify", exist_ok=True)

    # ---- Derive service keys from passwords/salts ----
    creds = {
        "krbtgt": (b"KrbtgtMasterKey2025!", b"ACME.CORPkrbtgt/ACME.CORP"),
        "HTTP":   (b"WebSvc!Pa55w0rd",      b"ACME.CORPHTTP/web01.acme.corp"),
        "LDAP":   (b"LdapDC01#Secret",      b"ACME.CORPLDAP/dc01.acme.corp"),
        "MSSQL":  (b"SqlSvc2025!Key",       b"ACME.CORPMSSQLSvc/db01.acme.corp"),
    }
    old_http_cred = (b"OldWebSvcP@ss!", b"ACME.CORPHTTP/web01.acme.corp")

    keys = {}
    for name, (pwd, salt) in creds.items():
        keys[(name, 18)] = Key.string_to_key(AES256, pwd, salt)
        keys[(name, 17)] = Key.string_to_key(AES128, pwd, salt)
    keys[("HTTP_old", 18)] = Key.string_to_key(AES256, *old_http_cred)

    print("Keys derived successfully")

    # ---- Build keytab files ----
    keytabs = {
        "dc01.keytab": [
            (["krbtgt", "ACME.CORP"], "ACME.CORP", 2, 2, 18,
             keys[("krbtgt", 18)].key),
            (["krbtgt", "ACME.CORP"], "ACME.CORP", 2, 2, 17,
             keys[("krbtgt", 17)].key),
            (["LDAP", "dc01.acme.corp"], "ACME.CORP", 2, 1, 18,
             keys[("LDAP", 18)].key),
            (["LDAP", "dc01.acme.corp"], "ACME.CORP", 2, 1, 17,
             keys[("LDAP", 17)].key),
        ],
        "web01.keytab": [
            (["HTTP", "web01.acme.corp"], "ACME.CORP", 2, 3, 18,
             keys[("HTTP", 18)].key),
            (["HTTP", "web01.acme.corp"], "ACME.CORP", 2, 3, 17,
             keys[("HTTP", 17)].key),
            (["HTTP", "web01.acme.corp"], "ACME.CORP", 2, 2, 18,
             keys[("HTTP_old", 18)].key),
        ],
        "db01.keytab": [
            (["MSSQLSvc", "db01.acme.corp"], "ACME.CORP", 2, 1, 18,
             keys[("MSSQL", 18)].key),
            (["MSSQLSvc", "db01.acme.corp"], "ACME.CORP", 2, 1, 17,
             keys[("MSSQL", 17)].key),
        ],
    }

    for fname, entries in keytabs.items():
        with open(f"/app/incident/keytabs/{fname}", "wb") as f:
            f.write(build_keytab(entries))
        print(f"  {fname}: {len(entries)} entries")

    # ---- Expected keytab summary (for verification) ----
    keytab_summary = {
        "dc01.keytab": [
            {"principal": "krbtgt/ACME.CORP@ACME.CORP", "etype": 18, "kvno": 2},
            {"principal": "krbtgt/ACME.CORP@ACME.CORP", "etype": 17, "kvno": 2},
            {"principal": "LDAP/dc01.acme.corp@ACME.CORP", "etype": 18, "kvno": 1},
            {"principal": "LDAP/dc01.acme.corp@ACME.CORP", "etype": 17, "kvno": 1},
        ],
        "web01.keytab": [
            {"principal": "HTTP/web01.acme.corp@ACME.CORP", "etype": 18, "kvno": 3},
            {"principal": "HTTP/web01.acme.corp@ACME.CORP", "etype": 17, "kvno": 3},
            {"principal": "HTTP/web01.acme.corp@ACME.CORP", "etype": 18, "kvno": 2},
        ],
        "db01.keytab": [
            {"principal": "MSSQLSvc/db01.acme.corp@ACME.CORP", "etype": 18, "kvno": 1},
            {"principal": "MSSQLSvc/db01.acme.corp@ACME.CORP", "etype": 17, "kvno": 1},
        ],
    }

    # ---- Build tickets ----
    # Flags: forwardable(1), proxiable(3), renewable(8), initial(9), pre-authent(10)
    normal_flags = b'\x50\xe0\x00\x00'

    ticket_specs = [
        # (name, sname_components, client, authtime, endtime,
        #  enc_key, etype, kvno, keytab)
        ("ticket_01", ["krbtgt", "ACME.CORP"], "jdoe",
         "20250315080000Z", "20250315180000Z",
         keys[("krbtgt", 18)], 18, 2, "dc01.keytab"),

        ("ticket_02", ["HTTP", "web01.acme.corp"], "jdoe",
         "20250315081500Z", "20250315181500Z",
         keys[("HTTP", 18)], 18, 3, "web01.keytab"),

        ("ticket_03", ["LDAP", "dc01.acme.corp"], "admin_svc",
         "20250315090000Z", "20250315190000Z",
         keys[("LDAP", 18)], 18, 1, "dc01.keytab"),

        ("ticket_04", ["krbtgt", "ACME.CORP"], "intruder",
         "20250315020000Z", "20260315020000Z",  # 365-day lifetime!
         keys[("krbtgt", 18)], 18, 2, "dc01.keytab"),

        ("ticket_05", ["MSSQLSvc", "db01.acme.corp"], "jdoe",
         "20250315100000Z", "20250315200000Z",
         keys[("MSSQL", 18)], 18, 1, "db01.keytab"),

        ("ticket_06", ["krbtgt", "ACME.CORP"], "intruder",
         "20250315023000Z", "20260315023000Z",  # 365-day lifetime!
         keys[("krbtgt", 17)], 17, 2, "dc01.keytab"),
    ]

    expected_details = {}

    for i, (name, sname_comps, client, authtime, endtime,
            enc_key, etype, kvno, keytab) in enumerate(ticket_specs):

        sk = SESSION_KEYS[i]
        sk_etype = 18  # all session keys are AES-256

        # Build EncTicketPart DER
        enc_tkt_der = build_enc_ticket_part(
            flags_bytes=normal_flags,
            session_key_bytes=sk,
            sk_etype=sk_etype,
            crealm="ACME.CORP",
            cname=client,
            authtime=authtime,
            endtime=endtime,
        )

        # Encrypt with service key (key_usage=2: ticket encryption)
        cipher = enc_key.encrypt(2, enc_tkt_der)

        # Verify round-trip decryption
        decrypted = enc_key.decrypt(2, cipher)
        assert decrypted == enc_tkt_der, f"Round-trip failed for {name}"

        # Build full KRB_Ticket DER
        ticket_der = build_krb_ticket(
            realm="ACME.CORP",
            sname_components=sname_comps,
            etype=etype,
            kvno=kvno,
            cipher_bytes=cipher,
        )

        with open(f"/app/incident/tickets/{name}.der", "wb") as f:
            f.write(ticket_der)

        svc = "/".join(sname_comps)
        expected_details[f"{name}.der"] = {
            "service_principal": svc,
            "client_principal": client,
            "client_realm": "ACME.CORP",
            "encryption_type": etype,
            "auth_time": authtime,
            "end_time": endtime,
            "decrypted_with_keytab": keytab,
            "session_key_hex": sk.hex(),
        }
        print(f"  {name}.der: {len(ticket_der)} bytes, svc={svc}, client={client}")

    # ---- Write manifest ----
    manifest = {
        "realm": "ACME.CORP",
        "known_users": ["jdoe", "admin_svc", "webmaster"],
        "description": (
            "Incident artifacts from the ACME.CORP Kerberos realm. "
            "Three keytab files were extracted from domain servers. "
            "Six Kerberos tickets were captured from network traffic "
            "during the incident window."
        ),
        "report_schema": {
            "keytab_summary": {
                "<keytab_filename>": [
                    {"principal": "<principal>@<realm>", "etype": "<int>", "kvno": "<int>"}
                ]
            },
            "ticket_decryptions": {
                "<ticket_filename>": {
                    "service_principal": "<SPN components joined with />",
                    "client_principal": "<client name from cname field>",
                    "client_realm": "<realm string from crealm field>",
                    "encryption_type": "<int: etype used to encrypt the ticket>",
                    "auth_time": "<YYYYMMDDHHmmSSZ format>",
                    "end_time": "<YYYYMMDDHHmmSSZ format>",
                    "decrypted_with_keytab": "<keytab filename that held the decryption key>",
                    "session_key_hex": "<hex-encoded session key bytes>"
                }
            },
            "anomalous_tickets": [
                "<sorted list of ticket filenames exhibiting compromise indicators>"
            ],
            "compromised_keytab": "<keytab filename most likely exfiltrated>",
            "attacker_principal": "<client principal name found in forged tickets>"
        },
    }
    with open("/app/incident/manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # ---- Write verification hashes ----
    def canonical(obj):
        return json.dumps(obj, sort_keys=True, separators=(',', ':'))

    checks = {"total_keytab_entries": 9}

    for tkt_name, details in expected_details.items():
        key = tkt_name.replace(".der", "")
        checks[f"{key}_hash"] = hashlib.sha256(
            canonical(details).encode()
        ).hexdigest()

    checks["anomalous_hash"] = hashlib.sha256(
        canonical(["ticket_04.der", "ticket_06.der"]).encode()
    ).hexdigest()
    checks["compromised_keytab_hash"] = hashlib.sha256(
        b"dc01.keytab"
    ).hexdigest()
    checks["attacker_principal_hash"] = hashlib.sha256(
        b"intruder"
    ).hexdigest()

    # Also store the keytab summary hash for verification
    checks["keytab_summary_hash"] = hashlib.sha256(
        canonical(keytab_summary).encode()
    ).hexdigest()

    with open("/var/lib/task_verify/checks.json", "w") as f:
        json.dump(checks, f, indent=2)

    print("\nChallenge generated successfully")
    print(f"  Keytab entries: 9")
    print(f"  Tickets: 6 (2 forged)")


if __name__ == "__main__":
    main()
