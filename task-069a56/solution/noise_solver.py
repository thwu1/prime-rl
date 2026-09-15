#!/usr/bin/env python3

"""
Noise Protocol Framework handshake state machine implementation.
Processes challenges from /app/challenges.json and writes results to /app/results.json.
"""

import hashlib
import hmac as hmac_mod
import json
import re
import struct

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


# ============================================================
# DH Functions (Curve25519)
# ============================================================

DHLEN = 32


def keypair_from_private(private_bytes):
    priv = X25519PrivateKey.from_private_bytes(private_bytes)
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return (priv, pub)


def dh(keypair, public_key_bytes):
    priv = keypair[0]
    pub = X25519PublicKey.from_public_bytes(public_key_bytes)
    return priv.exchange(pub)


# ============================================================
# Cipher Functions
# ============================================================


def chacha_encrypt(k, n, ad, plaintext):
    nonce = b"\x00" * 4 + struct.pack("<Q", n)
    return ChaCha20Poly1305(k).encrypt(nonce, plaintext, ad)


def chacha_decrypt(k, n, ad, ciphertext):
    nonce = b"\x00" * 4 + struct.pack("<Q", n)
    return ChaCha20Poly1305(k).decrypt(nonce, ciphertext, ad)


def aesgcm_encrypt(k, n, ad, plaintext):
    nonce = b"\x00" * 4 + struct.pack(">Q", n)
    return AESGCM(k).encrypt(nonce, plaintext, ad)


def aesgcm_decrypt(k, n, ad, ciphertext):
    nonce = b"\x00" * 4 + struct.pack(">Q", n)
    return AESGCM(k).decrypt(nonce, ciphertext, ad)


CIPHERS = {
    "ChaChaPoly": (chacha_encrypt, chacha_decrypt),
    "AESGCM": (aesgcm_encrypt, aesgcm_decrypt),
}

# ============================================================
# Hash Functions
# ============================================================

HASHES = {
    "SHA256": {
        "hashlen": 32,
        "blocklen": 64,
        "hash": lambda data: hashlib.sha256(data).digest(),
        "hmac": lambda key, data: hmac_mod.new(key, data, "sha256").digest(),
    },
    "SHA512": {
        "hashlen": 64,
        "blocklen": 128,
        "hash": lambda data: hashlib.sha512(data).digest(),
        "hmac": lambda key, data: hmac_mod.new(key, data, "sha512").digest(),
    },
    "BLAKE2s": {
        "hashlen": 32,
        "blocklen": 64,
        "hash": lambda data: hashlib.blake2s(data).digest(),
        "hmac": lambda key, data: hmac_mod.new(key, data, hashlib.blake2s).digest(),
    },
    "BLAKE2b": {
        "hashlen": 64,
        "blocklen": 128,
        "hash": lambda data: hashlib.blake2b(data).digest(),
        "hmac": lambda key, data: hmac_mod.new(key, data, hashlib.blake2b).digest(),
    },
}


# ============================================================
# HKDF
# ============================================================


def noise_hkdf(hash_fns, chaining_key, input_key_material, num_outputs):
    hmac_fn = hash_fns["hmac"]
    temp_key = hmac_fn(chaining_key, input_key_material)
    output1 = hmac_fn(temp_key, b"\x01")
    output2 = hmac_fn(temp_key, output1 + b"\x02")
    if num_outputs == 2:
        return output1, output2
    output3 = hmac_fn(temp_key, output2 + b"\x03")
    return output1, output2, output3


# ============================================================
# CipherState
# ============================================================


class CipherState:
    def __init__(self, encrypt_fn, decrypt_fn):
        self.encrypt_fn = encrypt_fn
        self.decrypt_fn = decrypt_fn
        self.k = None
        self.n = 0

    def initialize_key(self, key):
        self.k = key
        self.n = 0

    def has_key(self):
        return self.k is not None

    def encrypt_with_ad(self, ad, plaintext):
        if not self.has_key():
            return plaintext
        ct = self.encrypt_fn(self.k, self.n, ad, plaintext)
        self.n += 1
        return ct

    def decrypt_with_ad(self, ad, ciphertext):
        if not self.has_key():
            return ciphertext
        pt = self.decrypt_fn(self.k, self.n, ad, ciphertext)
        self.n += 1
        return pt


# ============================================================
# SymmetricState
# ============================================================


class SymmetricState:
    def __init__(self, hash_fns, encrypt_fn, decrypt_fn):
        self.hash_fns = hash_fns
        self.hashlen = hash_fns["hashlen"]
        self.cs = CipherState(encrypt_fn, decrypt_fn)
        self.ck = None
        self.h = None

    def initialize_symmetric(self, protocol_name):
        name_bytes = protocol_name.encode("ascii")
        if len(name_bytes) <= self.hashlen:
            self.h = name_bytes + b"\x00" * (self.hashlen - len(name_bytes))
        else:
            self.h = self.hash_fns["hash"](name_bytes)
        self.ck = self.h
        self.cs.initialize_key(None)

    def mix_key(self, ikm):
        self.ck, temp_k = noise_hkdf(self.hash_fns, self.ck, ikm, 2)
        if self.hashlen == 64:
            temp_k = temp_k[:32]
        self.cs.initialize_key(temp_k)

    def mix_hash(self, data):
        self.h = self.hash_fns["hash"](self.h + data)

    def mix_key_and_hash(self, ikm):
        self.ck, temp_h, temp_k = noise_hkdf(self.hash_fns, self.ck, ikm, 3)
        self.mix_hash(temp_h)
        if self.hashlen == 64:
            temp_k = temp_k[:32]
        self.cs.initialize_key(temp_k)

    def encrypt_and_hash(self, plaintext):
        ct = self.cs.encrypt_with_ad(self.h, plaintext)
        self.mix_hash(ct)
        return ct

    def decrypt_and_hash(self, ciphertext):
        pt = self.cs.decrypt_with_ad(self.h, ciphertext)
        self.mix_hash(ciphertext)
        return pt

    def split(self):
        temp_k1, temp_k2 = noise_hkdf(self.hash_fns, self.ck, b"", 2)
        if self.hashlen == 64:
            temp_k1 = temp_k1[:32]
            temp_k2 = temp_k2[:32]
        c1 = CipherState(self.cs.encrypt_fn, self.cs.decrypt_fn)
        c2 = CipherState(self.cs.encrypt_fn, self.cs.decrypt_fn)
        c1.initialize_key(temp_k1)
        c2.initialize_key(temp_k2)
        return c1, c2


# ============================================================
# Handshake Patterns
# ============================================================

# (initiator_pre_message, responder_pre_message, message_patterns)
PATTERNS = {
    "N": ([], ["s"], [["e", "es"]]),
    "K": (["s"], ["s"], [["e", "es", "ss"]]),
    "X": ([], ["s"], [["e", "es", "s", "ss"]]),
    "NN": ([], [], [["e"], ["e", "ee"]]),
    "NK": ([], ["s"], [["e", "es"], ["e", "ee"]]),
    "NX": ([], [], [["e"], ["e", "ee", "s", "es"]]),
    "KN": (["s"], [], [["e"], ["e", "ee", "se"]]),
    "KK": (["s"], ["s"], [["e", "es", "ss"], ["e", "ee", "se"]]),
    "KX": (["s"], [], [["e"], ["e", "ee", "se", "s", "es"]]),
    "XN": ([], [], [["e"], ["e", "ee"], ["s", "se"]]),
    "XK": ([], ["s"], [["e", "es"], ["e", "ee"], ["s", "se"]]),
    "XX": ([], [], [["e"], ["e", "ee", "s", "es"], ["s", "se"]]),
    "IN": ([], [], [["e", "s"], ["e", "ee", "se"]]),
    "IK": ([], ["s"], [["e", "es", "s", "ss"], ["e", "ee", "se"]]),
    "IX": ([], [], [["e", "s"], ["e", "ee", "se", "s", "es"]]),
}


def parse_pattern_name(pattern_section):
    """Parse e.g. 'NNpsk0' into ('NN', [0])."""
    parts = pattern_section.split("+")
    first = parts[0]
    base_end = len(first)
    for i, c in enumerate(first):
        if c.islower():
            base_end = i
            break
    base = first[:base_end]
    modifiers = []
    remainder = first[base_end:]
    if remainder:
        modifiers.append(remainder)
    for p in parts[1:]:
        modifiers.append(p)
    psk_positions = []
    for mod in modifiers:
        m = re.match(r"psk(\d+)", mod)
        if m:
            psk_positions.append(int(m.group(1)))
    return base, psk_positions


# ============================================================
# HandshakeState
# ============================================================


class HandshakeState:
    def __init__(self, hash_fns, encrypt_fn, decrypt_fn):
        self.ss = SymmetricState(hash_fns, encrypt_fn, decrypt_fn)
        self.s = None  # (priv_obj, pub_bytes)
        self.e = None  # (priv_obj, pub_bytes)
        self.rs = None  # pub_bytes
        self.re = None  # pub_bytes
        self.initiator = True
        self.message_patterns = []
        self.is_psk = False
        self.psks = []
        self.psk_idx = 0

    def initialize(
        self, protocol_name, initiator, prologue, s, e, rs, re, psks
    ):
        self.ss.initialize_symmetric(protocol_name)
        self.ss.mix_hash(prologue)
        self.initiator = initiator
        self.s = s
        self.e = e
        self.rs = rs
        self.re = re
        self.psks = psks or []
        self.psk_idx = 0

        pattern_section = protocol_name.split("_")[1]
        base_pattern, psk_positions = parse_pattern_name(pattern_section)
        self.is_psk = len(psk_positions) > 0

        init_pre, resp_pre, messages = PATTERNS[base_pattern]

        # Process initiator pre-messages
        for token in init_pre:
            if token == "s":
                if initiator:
                    self.ss.mix_hash(self.s[1])
                else:
                    self.ss.mix_hash(self.rs)
            elif token == "e":
                pub = self.e[1] if initiator else self.re
                self.ss.mix_hash(pub)
                if self.is_psk:
                    self.ss.mix_key(pub)

        # Process responder pre-messages
        for token in resp_pre:
            if token == "s":
                if initiator:
                    self.ss.mix_hash(self.rs)
                else:
                    self.ss.mix_hash(self.s[1])
            elif token == "e":
                pub = self.re if initiator else self.e[1]
                self.ss.mix_hash(pub)
                if self.is_psk:
                    self.ss.mix_key(pub)

        # Build message patterns with PSK tokens
        self.message_patterns = []
        for i, tokens in enumerate(messages):
            msg_tokens = list(tokens)
            for pos in psk_positions:
                if pos == 0 and i == 0:
                    msg_tokens.insert(0, "psk")
                elif pos == i + 1:
                    msg_tokens.append("psk")
            self.message_patterns.append(msg_tokens)

    def _process_dh_token(self, token):
        if token == "ee":
            self.ss.mix_key(dh(self.e, self.re))
        elif token == "es":
            if self.initiator:
                self.ss.mix_key(dh(self.e, self.rs))
            else:
                self.ss.mix_key(dh(self.s, self.re))
        elif token == "se":
            if self.initiator:
                self.ss.mix_key(dh(self.s, self.re))
            else:
                self.ss.mix_key(dh(self.e, self.rs))
        elif token == "ss":
            self.ss.mix_key(dh(self.s, self.rs))

    def write_message(self, payload):
        tokens = self.message_patterns.pop(0)
        buf = b""
        for token in tokens:
            if token == "e":
                assert self.e is not None, "Ephemeral key must be pre-set"
                buf += self.e[1]
                self.ss.mix_hash(self.e[1])
                if self.is_psk:
                    self.ss.mix_key(self.e[1])
            elif token == "s":
                buf += self.ss.encrypt_and_hash(self.s[1])
            elif token == "psk":
                self.ss.mix_key_and_hash(self.psks[self.psk_idx])
                self.psk_idx += 1
            else:
                self._process_dh_token(token)
        buf += self.ss.encrypt_and_hash(payload)
        split_result = None
        if not self.message_patterns:
            split_result = self.ss.split()
        return buf, split_result

    def read_message(self, message):
        tokens = self.message_patterns.pop(0)
        offset = 0
        for token in tokens:
            if token == "e":
                self.re = message[offset : offset + DHLEN]
                offset += DHLEN
                self.ss.mix_hash(self.re)
                if self.is_psk:
                    self.ss.mix_key(self.re)
            elif token == "s":
                length = DHLEN + 16 if self.ss.cs.has_key() else DHLEN
                temp = message[offset : offset + length]
                offset += length
                self.rs = self.ss.decrypt_and_hash(temp)
            elif token == "psk":
                self.ss.mix_key_and_hash(self.psks[self.psk_idx])
                self.psk_idx += 1
            else:
                self._process_dh_token(token)
        remaining = message[offset:]
        payload = self.ss.decrypt_and_hash(remaining)
        split_result = None
        if not self.message_patterns:
            split_result = self.ss.split()
        return payload, split_result


# ============================================================
# Simulation
# ============================================================


def simulate(challenge):
    parts = challenge["protocol_name"].split("_")
    cipher_name = parts[3]
    hash_name = parts[4]

    hash_fns = HASHES[hash_name]
    encrypt_fn, decrypt_fn = CIPHERS[cipher_name]

    pattern_section = parts[1]
    base_pattern, _ = parse_pattern_name(pattern_section)
    is_one_way = len(base_pattern) == 1

    # Prepare initiator keys
    init_s = None
    if challenge.get("init_static"):
        init_s = keypair_from_private(bytes.fromhex(challenge["init_static"]))
    init_e = None
    if challenge.get("init_ephemeral"):
        init_e = keypair_from_private(bytes.fromhex(challenge["init_ephemeral"]))
    init_rs = None
    if challenge.get("init_remote_static"):
        init_rs = bytes.fromhex(challenge["init_remote_static"])
    init_psks = [bytes.fromhex(p) for p in challenge.get("init_psks", [])]

    # Prepare responder keys
    resp_s = None
    if challenge.get("resp_static"):
        resp_s = keypair_from_private(bytes.fromhex(challenge["resp_static"]))
    resp_e = None
    if challenge.get("resp_ephemeral"):
        resp_e = keypair_from_private(bytes.fromhex(challenge["resp_ephemeral"]))
    resp_rs = None
    if challenge.get("resp_remote_static"):
        resp_rs = bytes.fromhex(challenge["resp_remote_static"])
    resp_psks = [bytes.fromhex(p) for p in challenge.get("resp_psks", [])]

    protocol_name = challenge["protocol_name"]
    init_prologue = bytes.fromhex(challenge["init_prologue"])
    resp_prologue = bytes.fromhex(challenge["resp_prologue"])

    # Initialize both handshake states
    init_hs = HandshakeState(hash_fns, encrypt_fn, decrypt_fn)
    init_hs.initialize(
        protocol_name, True, init_prologue, init_s, init_e, init_rs, None, init_psks
    )

    resp_hs = HandshakeState(hash_fns, encrypt_fn, decrypt_fn)
    resp_hs.initialize(
        protocol_name, False, resp_prologue, resp_s, resp_e, resp_rs, None, resp_psks
    )

    # Determine handshake message count
    _, _, pattern_msgs = PATTERNS[base_pattern]
    num_hs = len(pattern_msgs)

    payloads = challenge["payloads"]
    ciphertexts = []
    c1 = None
    c2 = None
    handshake_hash = None

    for i, payload_hex in enumerate(payloads):
        payload = bytes.fromhex(payload_hex)

        if i < num_hs:
            # Handshake message
            if i % 2 == 0:
                ct, split = init_hs.write_message(payload)
                resp_hs.read_message(ct)
            else:
                ct, split = resp_hs.write_message(payload)
                init_hs.read_message(ct)

            ciphertexts.append(ct.hex())

            if split is not None:
                c1, c2 = split
                writer_ss = init_hs.ss if i % 2 == 0 else resp_hs.ss
                handshake_hash = writer_ss.h
        else:
            # Transport message
            if is_one_way:
                ct = c1.encrypt_with_ad(b"", payload)
            elif i % 2 == 0:
                ct = c1.encrypt_with_ad(b"", payload)
            else:
                ct = c2.encrypt_with_ad(b"", payload)
            ciphertexts.append(ct.hex())

    return {
        "protocol_name": protocol_name,
        "handshake_hash": handshake_hash.hex(),
        "messages": [{"ciphertext": ct} for ct in ciphertexts],
    }


def main():
    with open("/app/challenges.json") as f:
        challenges = json.load(f)

    results = []
    for challenge in challenges:
        result = simulate(challenge)
        results.append(result)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
