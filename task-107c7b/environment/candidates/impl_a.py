"""TCP-AO candidate implementation A."""
import hmac
import hashlib
import struct
import socket


def _aes_encrypt(key, data):
    from Crypto.Cipher import AES
    return AES.new(key, AES.MODE_ECB).encrypt(data)


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def _lshift1(data):
    out = bytearray(16)
    carry = 0
    for i in range(15, -1, -1):
        out[i] = ((data[i] << 1) & 0xFF) | carry
        carry = 1 if (data[i] & 0x80) else 0
    return bytes(out)


_Z16 = b'\x00' * 16
_RB = b'\x00' * 15 + b'\x87'


def _cmac_subkeys(key):
    L = _aes_encrypt(key, _Z16)
    K1 = _lshift1(L)
    if L[0] & 0x80:
        K1 = _xor(K1, _RB)
    K2 = _lshift1(K1)
    if K1[0] & 0x80:
        K2 = _xor(K2, _RB)
    return K1, K2


def aes_128_cmac(key, msg):
    assert len(key) == 16
    K1, K2 = _cmac_subkeys(key)
    n = max(1, (len(msg) + 15) // 16)
    complete = len(msg) > 0 and len(msg) % 16 == 0
    if complete:
        M_last = _xor(msg[(n - 1) * 16:n * 16], K1)
    else:
        rem = msg[(n - 1) * 16:]
        padded = rem + b'\x80' + b'\x00' * (15 - len(rem))
        M_last = _xor(padded, K2)
    X = _Z16
    for i in range(n - 1):
        X = _aes_encrypt(key, _xor(X, msg[i * 16:(i + 1) * 16]))
    return _aes_encrypt(key, _xor(X, M_last))


_LABEL = b"TCP-AO"


def _enc_len(bits):
    return struct.pack('>H', bits)


def _kdf_hmac_sha1(mk, ctx, outbits=160):
    enc = _enc_len(outbits)
    result = b""
    iters = (outbits + 159) // 160
    for i in range(1, iters + 1):
        block = bytes([i]) + _LABEL + ctx + enc
        result += hmac.new(mk, block, hashlib.sha1).digest()
    return result[:outbits // 8]


def _kdf_aes_cmac(mk, ctx, outbits=128):
    K = mk if len(mk) == 16 else aes_128_cmac(_Z16, mk)
    enc = _enc_len(outbits)
    result = b""
    iters = (outbits + 127) // 128
    for i in range(1, iters + 1):
        block = bytes([i]) + _LABEL + ctx + enc
        result += aes_128_cmac(K, block)
    return result[:outbits // 8]


def _ip2b(ip):
    if ':' in ip:
        return socket.inet_pton(socket.AF_INET6, ip)
    return socket.inet_pton(socket.AF_INET, ip)


def derive_traffic_key(kdf_alg, master_key, src_ip, dst_ip,
                       src_port, dst_port, src_isn, dst_isn):
    ctx = (_ip2b(src_ip) + _ip2b(dst_ip) +
           struct.pack('!HH', src_port, dst_port) +
           struct.pack('!II', src_isn, dst_isn))
    if kdf_alg == "HMAC-SHA1":
        return _kdf_hmac_sha1(master_key, ctx)
    elif kdf_alg == "AES-128-CMAC":
        return _kdf_aes_cmac(master_key, ctx)
    raise ValueError(f"Unknown KDF: {kdf_alg}")


def compute_mac(mac_alg, traffic_key, message):
    if mac_alg == "HMAC-SHA-1-96":
        return hmac.new(traffic_key, message, hashlib.sha1).digest()[:12]
    elif mac_alg == "AES-128-CMAC-96":
        return aes_128_cmac(traffic_key, message)[:12]
    raise ValueError(f"Unknown MAC: {mac_alg}")
