#!/usr/bin/env python3

"""
Generate RSA public key files, challenge ciphertexts, and metadata
for the RSA key infrastructure audit task.

No external dependencies required - uses manual DER/PEM encoding.
"""

import base64
import hashlib
import json
import os


# ── DER / PEM encoding helpers ──────────────────────────────────────────────

def _encode_length(n):
    if n < 128:
        return bytes([n])
    length_bytes = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(length_bytes)]) + length_bytes


def _encode_integer(n):
    if n == 0:
        value = b"\x00"
    else:
        value = n.to_bytes((n.bit_length() + 7) // 8, "big")
        if value[0] & 0x80:
            value = b"\x00" + value
    return b"\x02" + _encode_length(len(value)) + value


def _encode_sequence(contents):
    return b"\x30" + _encode_length(len(contents)) + contents


def _encode_bit_string(data):
    return b"\x03" + _encode_length(len(data) + 1) + b"\x00" + data


def rsa_spki_der(n, e):
    """Encode RSA public key as SubjectPublicKeyInfo DER."""
    rsa_pub = _encode_sequence(_encode_integer(n) + _encode_integer(e))
    oid = bytes([0x06, 0x09, 0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 0x01, 0x01, 0x01])
    alg = _encode_sequence(oid + b"\x05\x00")
    return _encode_sequence(alg + _encode_bit_string(rsa_pub))


def rsa_spki_pem(n, e):
    """Encode RSA public key as SubjectPublicKeyInfo PEM."""
    der = rsa_spki_der(n, e)
    b64 = base64.encodebytes(der).decode("ascii")
    return "-----BEGIN PUBLIC KEY-----\n" + b64 + "-----END PUBLIC KEY-----\n"


def rsa_pkcs1_pem(n, e):
    """Encode RSA public key as PKCS#1 RSAPublicKey PEM."""
    der = _encode_sequence(_encode_integer(n) + _encode_integer(e))
    b64 = base64.encodebytes(der).decode("ascii")
    return "-----BEGIN RSA PUBLIC KEY-----\n" + b64 + "-----END RSA PUBLIC KEY-----\n"


# ── Key definitions ─────────────────────────────────────────────────────────
# Each entry: (p, q, e, file_format)
#   file_format: "spki_pem", "pkcs1_pem", or "spki_der"

KEYS = {
    "cert_01": (
        74702390813723807004418547,
        158623786610890603447264381,
        65537,
        "spki_pem",
    ),
    "cert_02": (
        137461851857785797786497745150471556824442572406264153467249512336332042578425214140213641168605935190505736202414886783409882492073681041616726756355425494675925358963681127461123718595353714557996344684151465911758163193881127145775606843294621089662937571258147846396896041767733660808035742923420580946767,
        150070438827931342639471779076429081456862442338581599294185467390936345390926336742376257036838776214169949858905524253415852897746374935080267629528016195185804524866726113410870993510542203419696639390087164987019733148934440188299315356157574153412293128940096367197835678775078803327833176244502571632751,
        65537,
        "pkcs1_pem",
    ),
    "cert_03": (
        59425145566653111326058274838888770296983390977636816588557292076825683441217,
        75505855906477749881218532369719632982711167694549371844153183771219399935323,
        65537,
        "spki_der",
    ),
    "cert_04": (
        8183157034452981267761513,
        186902683488084340785509029,
        65537,
        "spki_pem",
    ),
    "cert_05": (
        121362572135823744443553644986516743994252568796262907800162656229396415053561693139873861374415079501745616992716448525837420635036342983029692709385585327975168754001034779927413176310882798415562873082815210101882445039267280721092786148397514001449284333523370932220009983150195447618621814380435779685317,
        102521562904519454682538417856032349193272396082821266018483159425470079764770249773293395540597848417831047030690342527797457598217240122174679421264303521592809479784502138981851720878392267161466366873474076676652696127502248187426461815148246372805966415448695761519977374606044058472724012799062613913797,
        65537,
        "spki_pem",
    ),
    "cert_06": (
        106341978143635167472157361088514721898453747878982910791080638747424114477937,
        106341978143635167472157361088514721898453747878982910791080638747424114478007,
        65537,
        "spki_der",
    ),
    "cert_07": (
        13377761418820405685455939,
        547221705184960646421168589,
        65537,
        "pkcs1_pem",
    ),
    "cert_08": (
        168219106821476897533548427376392555369102214784655764189693459901728953554464833248553100556393470492829421568427316386262032692494515227443683581129142791102746524277738754119305173745228714647336702504826701806730358068515185172901546841569360144515213990908260063689717000934754635453612064084387464104081,
        115455897263161337004695175190043965678706177133712260889161525695254950050394004644718366908377511097088072020610983842696941819461552330368916463247629740373402260932934264435613352398445007338603987960181965350273502928521712857404352712211023815349021174682539091625528933393908329629037041529602286577461,
        65537,
        "spki_der",
    ),
    "cert_09": (
        59425145566653111326058274838888770296983390977636816588557292076825683441217,
        70171312020624364574787599938717148180695187528957400053463349809674317694939,
        65537,
        "spki_pem",
    ),
    "cert_10": (
        115503299065859120666865365349532429134765876168118003295243639150957122742420775338637320818674055377675724647107631117506858495359426414491254169465633446554604468408608480849116557628194499340433546332045961510746151977739483966791440267731177056756405238910110335901826380183722758521148303182001427363531,
        154911187380066483453864173823623278741031945580990467427501535271708750362689582745303364392597382999917561350269106335180593509683325382434710847936303376632973311930740794249432563371775881320776312126506925605716586343453238496483166981860573392904543081954708048785083448904692025564859655030195053785309,
        65537,
        "spki_pem",
    ),
}

METADATA = {
    "inventory_date": "2024-08-15",
    "exported_by": "key-mgmt-export v3.2.1",
    "keys": {
        "cert_01": {
            "origin": "hardware_tpm",
            "module": "Infineon SLB 9665 TT 2.0",
            "firmware": "7.40.2098.0",
            "generation_date": "2017-03-15",
            "purpose": "document_signing",
            "department": "legal",
        },
        "cert_02": {
            "origin": "software",
            "module": "OpenSSL 3.0.2",
            "firmware": None,
            "generation_date": "2022-01-10",
            "purpose": "tls_server",
            "department": "engineering",
        },
        "cert_03": {
            "origin": "hardware_hsm",
            "module": "KeyVault FPGA Module",
            "firmware": "2.1.3-beta",
            "generation_date": "2019-06-20",
            "purpose": "api_authentication",
            "department": "platform",
        },
        "cert_04": {
            "origin": "hardware_tpm",
            "module": "Infineon SLB 9665 TT 2.0",
            "firmware": "7.40.2098.0",
            "generation_date": "2017-04-02",
            "purpose": "email_signing",
            "department": "hr",
        },
        "cert_05": {
            "origin": "software",
            "module": "BoringSSL",
            "firmware": None,
            "generation_date": "2023-05-18",
            "purpose": "tls_server",
            "department": "engineering",
        },
        "cert_06": {
            "origin": "hardware_embedded",
            "module": "Custom Embedded RSA Module",
            "firmware": "0.9.4-alpha",
            "generation_date": "2016-11-12",
            "purpose": "device_identity",
            "department": "iot",
        },
        "cert_07": {
            "origin": "hardware_tpm",
            "module": "Infineon SLB 9665 TT 2.0",
            "firmware": "7.40.2098.0",
            "generation_date": "2017-05-11",
            "purpose": "code_signing",
            "department": "engineering",
        },
        "cert_08": {
            "origin": "software",
            "module": "OpenSSL 3.2.0",
            "firmware": None,
            "generation_date": "2024-02-14",
            "purpose": "tls_server",
            "department": "engineering",
        },
        "cert_09": {
            "origin": "hardware_hsm",
            "module": "KeyVault FPGA Module",
            "firmware": "2.1.3-beta",
            "generation_date": "2019-07-05",
            "purpose": "api_authentication",
            "department": "platform",
        },
        "cert_10": {
            "origin": "software",
            "module": "OpenSSL 3.3.1",
            "firmware": None,
            "generation_date": "2024-06-01",
            "purpose": "tls_server",
            "department": "operations",
        },
    },
}


def main():
    os.makedirs("/app/keys", exist_ok=True)
    os.makedirs("/app/challenges", exist_ok=True)
    os.makedirs("/app/results", exist_ok=True)

    for cert_id, (p, q, e, fmt) in sorted(KEYS.items()):
        n = p * q

        # Write public key file
        if fmt == "spki_pem":
            path = f"/app/keys/{cert_id}.pem"
            with open(path, "w") as f:
                f.write(rsa_spki_pem(n, e))
        elif fmt == "pkcs1_pem":
            path = f"/app/keys/{cert_id}.pem"
            with open(path, "w") as f:
                f.write(rsa_pkcs1_pem(n, e))
        elif fmt == "spki_der":
            path = f"/app/keys/{cert_id}.der"
            with open(path, "wb") as f:
                f.write(rsa_spki_der(n, e))

        # Generate challenge ciphertext: c = m^e mod n
        m = int(hashlib.sha256(f"CHALLENGE_{cert_id}".encode()).hexdigest(), 16) % (2**64)
        c = pow(m, e, n)
        with open(f"/app/challenges/{cert_id}.json", "w") as f:
            json.dump({"ciphertext": str(c)}, f, indent=2)

        print(f"  {cert_id}: {fmt}, {n.bit_length()}-bit modulus")

    # Write metadata
    with open("/app/metadata.json", "w") as f:
        json.dump(METADATA, f, indent=2)

    # Write audit scope document
    with open("/app/audit_scope.txt", "w") as f:
        f.write(
            "SECURITY ASSESSMENT: RSA KEY INFRASTRUCTURE\n"
            "============================================\n\n"
            "Scope: All RSA public keys in the organization's PKI inventory.\n\n"
            "Context: During a vendor-mandated firmware review, concerns were\n"
            "raised about the cryptographic key material generated by various\n"
            "hardware and software systems deployed across the organization.\n"
            "Some hardware modules may be affected by known firmware\n"
            "vulnerabilities. Additionally, an internal review of the custom\n"
            "HSM infrastructure revealed potential issues with entropy sources\n"
            "and key generation procedures.\n\n"
            "Deliverables:\n"
            " - Classification of each key as vulnerable or not\n"
            " - For each vulnerable key: demonstrate exploitation by\n"
            "   decrypting the corresponding challenge ciphertext\n\n"
            "Key files: /app/keys/\n"
            "Challenge ciphertexts: /app/challenges/\n"
            "Provenance metadata: /app/metadata.json\n"
        )

    print("Setup complete.")


if __name__ == "__main__":
    main()
