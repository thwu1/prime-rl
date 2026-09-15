"""Generate binary artifacts (DER key and PCAP capture) from public parameters.
Run during Docker build to avoid binary file corruption issues.
Contains ONLY public key parameters - no secrets.
"""
import struct
import json


def int_to_der_bytes(value):
    if value == 0:
        return b'\x00'
    hex_str = format(value, 'x')
    if len(hex_str) % 2:
        hex_str = '0' + hex_str
    raw = bytes.fromhex(hex_str)
    if raw[0] & 0x80:
        raw = b'\x00' + raw
    return raw


def der_encode_length(length):
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return bytes([0x81, length])
    else:
        return bytes([0x82, (length >> 8) & 0xff, length & 0xff])


def der_integer(value):
    raw = int_to_der_bytes(value)
    return b'\x02' + der_encode_length(len(raw)) + raw


def der_sequence(contents):
    return b'\x30' + der_encode_length(len(contents)) + contents


def der_bitstring(contents):
    body = b'\x00' + contents
    return b'\x03' + der_encode_length(len(body)) + body


def generate_der_key(n, e, output_path):
    RSA_OID = bytes([0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d,
                     0x01, 0x01, 0x01])
    NULL = b'\x05\x00'
    rsa_key_seq = der_sequence(der_integer(n) + der_integer(e))
    algo_id = der_sequence(RSA_OID + NULL)
    spki = der_sequence(algo_id + der_bitstring(rsa_key_seq))
    with open(output_path, 'wb') as f:
        f.write(spki)


def generate_pcap(packets_json, output_path):
    pcap = struct.pack('<IHHiIII',
                       0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
    for i, payload_text in enumerate(packets_json):
        payload_bytes = payload_text.encode('utf-8')
        udp_header = struct.pack('>HHHH', 31337, 31338,
                                 8 + len(payload_bytes), 0)
        ip_total_len = 20 + len(udp_header) + len(payload_bytes)
        ip_header = struct.pack('>BBHHHBBH4s4s',
                                0x45, 0x00, ip_total_len, 0x0000, 0x4000,
                                64, 17, 0,
                                bytes([10, 0, 0, 1]),
                                bytes([10, 0, 0, 2]))
        eth_header = (b'\x00\x00\x00\x00\x00\x02'
                      b'\x00\x00\x00\x00\x00\x01'
                      b'\x08\x00')
        packet = eth_header + ip_header + udp_header + payload_bytes
        pcap += struct.pack('<IIII', 1700000000 + i, 0,
                            len(packet), len(packet))
        pcap += packet
    with open(output_path, 'wb') as f:
        f.write(pcap)


# Party 4: DER-encoded SubjectPublicKeyInfo (Wiener-vulnerable: large e, small d)
N4 = int("5530412822818013977871448373810662478402536978687074658853858687"
         "4853562532168813133924847568745543548370923789181943145391253475"
         "96331243057763501507796537")
E4 = int("3240322975010107476587885186595729589169893926573710575597057280"
         "3163131470032061725461984559119925286091716821538182553848764558"
         "61447198654192122155134871")

generate_der_key(N4, E4, "/app/keys/party4_pub.der")

# Party 5: PCAP with UDP JSON payloads (Pollard p-1 vulnerable)
N5 = int("4319073273497040331277231882483628573150576076539268087340873486"
         "4918059896368212947975136559203607229964562450002227757643268547"
         "30393812081459447278637019")
E5 = 65537
ENC5 = int("406725061887781340741154233767312003818215347043600548034005441"
           "3471215850350271643707480304679486791054471590826440177765144725"
           "354027758112672599711441571")

json1 = json.dumps({"type": "KEY_EXCHANGE", "party_id": 5,
                     "party_name": "Epsilon Custodian",
                     "public_key": {"n": str(N5), "e": str(E5)},
                     "timestamp": "2023-11-14T12:00:01Z"})
json2 = json.dumps({"type": "ENCRYPTED_SHARE_TRANSFER", "party_id": 5,
                     "encrypted_share": str(ENC5),
                     "timestamp": "2023-11-14T12:00:02Z"})

generate_pcap([json1, json2], "/app/captures/share_transfer.pcap")
