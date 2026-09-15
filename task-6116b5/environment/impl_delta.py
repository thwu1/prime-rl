"""QUIC Packet Protection - Implementation Delta"""
import hmac, hashlib, struct
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

def _hkdf_extract(salt, ikm):
    return hmac.new(salt, ikm, hashlib.sha256).digest()

def _hkdf_expand(prk, info, length):
    n = (length + 31) // 32
    okm, t = b"", b""
    for i in range(1, n + 1):
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]

def _hkdf_expand_label(secret, label, ctx, length):
    tls_label = b"tls13 " + label.encode()
    info = (struct.pack(">H", length) + bytes([len(tls_label)])
            + tls_label + bytes([len(ctx)]) + ctx)
    return _hkdf_expand(secret, info, length)

_V1_SALT = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")
_V2_SALT = bytes.fromhex("0dede3def700a6db819381be6e269dcbf9bd2ed9")

def derive_initial_keys(dcid, version):
    salt = _V1_SALT if version == 1 else _V2_SALT
    kl, il, hl = (("quic key", "quic iv", "quic hp") if version == 1
                  else ("quicv2 key", "quicv2 iv", "quicv2 hp"))
    initial_secret = _hkdf_extract(salt, dcid)
    cs = _hkdf_expand_label(initial_secret, "client in", b"", 32)
    ss = _hkdf_expand_label(initial_secret, "server in", b"", 32)
    return {
        "initial_secret": initial_secret,
        "client_initial_secret": cs, "server_initial_secret": ss,
        "client_key": _hkdf_expand_label(cs, kl, b"", 16),
        "client_iv": _hkdf_expand_label(cs, il, b"", 12),
        "client_hp": _hkdf_expand_label(cs, hl, b"", 16),
        "server_key": _hkdf_expand_label(ss, kl, b"", 16),
        "server_iv": _hkdf_expand_label(ss, il, b"", 12),
        "server_hp": _hkdf_expand_label(ss, hl, b"", 16),
    }

def derive_keys_from_secret(secret, version, key_len):
    kl, il, hl, ul = (("quic key", "quic iv", "quic hp", "quic ku") if version == 1
                       else ("quicv2 key", "quicv2 iv", "quicv2 hp", "quicv2 ku"))
    return {
        "key": _hkdf_expand_label(secret, kl, b"", key_len),
        "iv": _hkdf_expand_label(secret, il, b"", 12),
        "hp": _hkdf_expand_label(secret, hl, b"", key_len),
        "ku": _hkdf_expand_label(secret, ul, b"", key_len),
    }

def protect_initial_packet(header, payload, key, iv, hp):
    pn_length = (header[0] & 0x03) + 1
    pn_offset = len(header) - pn_length
    pn = int.from_bytes(header[pn_offset:], "big")
    nonce = bytes(a ^ b for a, b in zip(iv, pn.to_bytes(len(iv), "big")))
    ct = AESGCM(key).encrypt(nonce, payload, header)
    packet = bytearray(header + ct)
    sample = bytes(packet[pn_offset + 3:pn_offset + 19])
    enc = Cipher(algorithms.AES(hp), modes.ECB()).encryptor()
    mask = enc.update(sample) + enc.finalize()
    packet[0] ^= mask[0] & 0x0f
    for i in range(pn_length):
        packet[pn_offset + i] ^= mask[1 + i]
    return bytes(packet)

def compute_retry_integrity_tag(odcid, retry_no_tag, version):
    if version == 1:
        rk = bytes.fromhex("be0c690b9f66575a1d766b54e368c84e")
        rn = bytes.fromhex("461599d35d632bf2239825bb")
    else:
        rk = bytes.fromhex("8fb4b01b56ac48e260fbcbcead7ccc92")
        rn = bytes.fromhex("d86969bc2d7c6d9990efb04a")
    pseudo = bytes([len(odcid)]) + odcid + retry_no_tag
    return AESGCM(rk).encrypt(rn, b"", pseudo)

def protect_short_header_chacha20(header, payload, pn, key, iv, hp):
    nonce = bytes(a ^ b for a, b in zip(iv, pn.to_bytes(len(iv), "big")))
    ct = ChaCha20Poly1305(key).encrypt(nonce, payload, header)
    pn_length = (header[0] & 0x03) + 1
    pn_offset = len(header) - pn_length
    packet = bytearray(header + ct)
    sample = bytes(packet[pn_offset + 4:pn_offset + 20])
    enc = Cipher(algorithms.ChaCha20(hp, sample), mode=None).encryptor()
    mask = enc.update(b"\x00" * 5)
    packet[0] ^= mask[0] & 0x1f
    for i in range(pn_length):
        packet[pn_offset + i] ^= mask[1 + i]
    return bytes(packet)
