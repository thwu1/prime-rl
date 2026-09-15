#!/usr/bin/env python3
"""Generate encrypted file corpus for recovery task."""
import os, sys, hashlib, random, subprocess, base64
import hmac as _hmac
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

_CS = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

def _bp(values):
    g = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    c = 1
    for v in values:
        b = c >> 25
        c = ((c & 0x1ffffff) << 5) ^ v
        for i in range(5):
            c ^= g[i] if ((b >> i) & 1) else 0
    return c

def _bd(s):
    s = s.lower()
    p = s.rfind("1")
    dp = s[p + 1:]
    d = [_CS.index(c) for c in dp]
    return d[:-6]

def _cb(data, fb, tb, pad=True):
    a, b, r, mx = 0, 0, [], (1 << tb) - 1
    for v in data:
        a = (a << fb) | v
        b += fb
        while b >= tb:
            b -= tb
            r.append((a >> b) & mx)
    if pad and b:
        r.append((a << (tb - b)) & mx)
    return r

def _priv(line):
    d5 = _bd(line.strip())
    d8 = _cb(d5, 5, 8, pad=False)
    return X25519PrivateKey.from_private_bytes(bytes(d8[:32]))

def _b64(d):
    return base64.b64encode(d).rstrip(b"=").decode()

def _hkdf(ikm, salt, info, l=32):
    if not salt:
        salt = b"\x00" * 32
    prk = _hmac.new(salt, ikm, hashlib.sha256).digest()
    t, o = b"", b""
    for i in range(1, (l + 31) // 32 + 1):
        t = _hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        o += t
    return o[:l]

def _enc(pt, rpub, mode=0):
    ek = X25519PrivateKey.generate()
    ep = ek.public_key().public_bytes_raw()
    rp = X25519PublicKey.from_public_bytes(rpub)
    ss = ek.exchange(rp)
    fk = os.urandom(16)

    ws = (rpub + ep) if mode == 1 else (ep + rpub)
    wi = b"age-encryption.org/v1" if mode == 2 else b"age-encryption.org/v1/X25519"
    wk = _hkdf(ss, ws, wi)
    wb = ChaCha20Poly1305(wk).encrypt(b"\x00" * 12, fk, None)

    ln = ["age-encryption.org/v1", "-> X25519 " + _b64(ep)]
    bb = _b64(wb)
    for i in range(0, len(bb), 64):
        ln.append(bb[i:i + 64])
    if not ln[-1] or len(ln[-1]) == 64:
        ln.append("")
    hdr = "\n".join(ln) + "\n---"
    mk = _hkdf(fk, b"", b"header")
    mc = _hmac.new(mk, hdr.encode(), hashlib.sha256).digest()
    full = hdr + " " + _b64(mc) + "\n"

    pn = os.urandom(16)
    pk = _hkdf(fk, pn, b"payload")
    ae = ChaCha20Poly1305(pk)
    out = bytearray(full.encode())
    out.extend(pn)
    off, ctr = 0, 0
    while True:
        ch = pt[off:off + 65536]
        fn = off + 65536 >= len(pt)
        cb = ctr.to_bytes(11, "little") if mode == 3 else ctr.to_bytes(11, "big")
        nn = cb + (b"\x01" if fn else b"\x00")
        out.extend(ae.encrypt(nn, bytes(ch), None))
        if fn:
            break
        off += 65536
        ctr += 1
    return bytes(out)

def main():
    os.makedirs("/app/corpus", exist_ok=True)
    r = subprocess.run(["age-keygen"], capture_output=True, text=True, check=True)
    ident = recip = None
    for ln in r.stdout.strip().splitlines():
        if ln.startswith("# public key: "):
            recip = ln.split(": ", 1)[1].strip()
        elif ln.upper().startswith("AGE-SECRET-KEY-"):
            ident = ln.strip()
    with open("/app/identity.key", "w") as f:
        f.write("# identity\n" + ident + "\n")
    pk = _priv(ident)
    pub = pk.public_key().public_bytes_raw()

    rng = random.Random(7439201)
    tk = [f"RECOVERED-{rng.randint(100000,999999):06d}" for _ in range(5)]

    for i, n in enumerate(["file_alpha", "file_beta"]):
        pt = f"Payload content.\nToken: {tk[i]}\n".encode()
        subprocess.run(["age", "-r", recip, "-o", f"/app/corpus/{n}.age"],
                       input=pt, check=True)

    for i, (n, m) in enumerate([("file_gamma", 1), ("file_delta", 2), ("file_epsilon", 3)]):
        if m == 3:
            rng2 = random.Random(99887766)
            pad = bytes(rng2.getrandbits(8) for _ in range(80000))
            pt = f"Token: {tk[i+2]}\n".encode() + pad
        else:
            pt = f"Token: {tk[i+2]}\n".encode()
        with open(f"/app/corpus/{n}.age", "wb") as f:
            f.write(_enc(pt, pub, mode=m))

    print(f"Done: {len(os.listdir('/app/corpus/'))} files")

if __name__ == "__main__":
    main()
