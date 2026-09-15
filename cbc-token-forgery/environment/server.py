#!/usr/bin/env python3
"""
Cryptographic token authentication service.
Uses AES-128-CBC with PKCS#7 padding for session token encryption.
"""

import os
import hashlib
import binascii
from flask import Flask, request, jsonify
from Crypto.Cipher import AES

app = Flask(__name__)
BLOCK = 16

STATE_DIR = "/app/.state"
os.makedirs(STATE_DIR, exist_ok=True)

_kp = os.path.join(STATE_DIR, "key.bin")
if os.path.exists(_kp):
    with open(_kp, "rb") as _f:
        _K = _f.read(16)
else:
    _K = os.urandom(16)
    with open(_kp, "wb") as _f:
        _f.write(_K)

_FLAG = "TBFLAG-" + hashlib.sha256(_K).hexdigest()[:32]


def _pad(d):
    n = BLOCK - (len(d) % BLOCK)
    return d + bytes([n] * n)


def _unpad(d):
    if not d or len(d) % BLOCK != 0:
        raise ValueError("length")
    n = d[-1]
    if n < 1 or n > BLOCK:
        raise ValueError("range")
    if d[-n:] != bytes([n] * n):
        raise ValueError("pad")
    return d[:-n]


def _enc(pt):
    iv = os.urandom(BLOCK)
    c = AES.new(_K, AES.MODE_CBC, iv)
    return iv + c.encrypt(_pad(pt))


def _dec(ct):
    if len(ct) < 2 * BLOCK or len(ct) % BLOCK != 0:
        raise ValueError("ct_len")
    iv, body = ct[:BLOCK], ct[BLOCK:]
    c = AES.new(_K, AES.MODE_CBC, iv)
    return _unpad(c.decrypt(body))


def _parse(raw):
    out = {}
    for seg in raw.decode("ascii").split("&"):
        if "=" in seg:
            k, v = seg.split("=", 1)
            out[k] = v
    return out


@app.route("/api/token", methods=["GET"])
def issue():
    nonce = binascii.hexlify(os.urandom(8)).decode()
    pt = f"priv=basic&user=guest&nonce={nonce}".encode()
    return jsonify({"token": _enc(pt).hex()})


@app.route("/api/verify", methods=["POST"])
def verify():
    body = request.get_json(silent=True) or {}
    tok = body.get("token", "")
    try:
        ct = bytes.fromhex(tok)
    except Exception:
        return jsonify({"error": "bad_hex"}), 400
    try:
        pt = _dec(ct)
    except ValueError:
        return jsonify({"error": "decrypt_fail"}), 500
    try:
        p = _parse(pt)
    except Exception:
        return jsonify({"error": "parse_fail"}), 400
    if p.get("priv") == "admin":
        return jsonify({"flag": _FLAG}), 200
    return jsonify({"error": "access_denied", "priv": p.get("priv", "")}), 403


@app.route("/api/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
