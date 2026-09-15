#!/usr/bin/env python3

"""
Noise Protocol Framework engine for forensic session analysis.

Implements the full Noise handshake state machine per spec revision 34,
supporting Curve25519 DH, ChaChaPoly/AESGCM ciphers, SHA256/BLAKE2s/BLAKE2b
hash functions, and PSK modifiers.
"""

import hashlib
import struct
import json
import sys

from nacl.bindings import crypto_scalarmult_base, crypto_scalarmult
from cryptography.hazmat.primitives.ciphers.aead import (
    ChaCha20Poly1305,
    AESGCM,
)


# ============================================================
# Hash Functions
# ============================================================

class SHA256Hash:
    HASHLEN = 32
    BLOCKLEN = 64
    NAME = "SHA256"

    @staticmethod
    def hash(data):
        return hashlib.sha256(data).digest()


class BLAKE2sHash:
    HASHLEN = 32
    BLOCKLEN = 64
    NAME = "BLAKE2s"

    @staticmethod
    def hash(data):
        return hashlib.blake2s(data).digest()


class BLAKE2bHash:
    HASHLEN = 64
    BLOCKLEN = 128
    NAME = "BLAKE2b"

    @staticmethod
    def hash(data):
        return hashlib.blake2b(data).digest()


# ============================================================
# HMAC and HKDF (manually implemented for BLAKE2 compat)
# ============================================================

def hmac_hash(hash_cls, key, data):
    """HMAC per RFC 2104 using the given hash function."""
    blocklen = hash_cls.BLOCKLEN
    if len(key) > blocklen:
        key = hash_cls.hash(key)
    key = key.ljust(blocklen, b'\x00')
    opad = bytes(b ^ 0x5c for b in key)
    ipad = bytes(b ^ 0x36 for b in key)
    return hash_cls.hash(opad + hash_cls.hash(ipad + data))


def hkdf(hash_cls, chaining_key, input_key_material, num_outputs):
    """HKDF as defined in the Noise spec (RFC 5869 with salt=chaining_key, info=empty)."""
    temp_key = hmac_hash(hash_cls, chaining_key, input_key_material)
    output1 = hmac_hash(hash_cls, temp_key, b'\x01')
    output2 = hmac_hash(hash_cls, temp_key, output1 + b'\x02')
    if num_outputs == 2:
        return output1, output2
    output3 = hmac_hash(hash_cls, temp_key, output2 + b'\x03')
    return output1, output2, output3


# ============================================================
# Cipher Functions
# ============================================================

class ChaChaPoly:
    NAME = "ChaChaPoly"

    @staticmethod
    def encrypt(k, n, ad, plaintext):
        nonce = b'\x00\x00\x00\x00' + struct.pack('<Q', n)
        return ChaCha20Poly1305(k).encrypt(nonce, plaintext, ad)

    @staticmethod
    def decrypt(k, n, ad, ciphertext):
        nonce = b'\x00\x00\x00\x00' + struct.pack('<Q', n)
        return ChaCha20Poly1305(k).decrypt(nonce, ciphertext, ad)


class AESGCMCipher:
    NAME = "AESGCM"

    @staticmethod
    def encrypt(k, n, ad, plaintext):
        nonce = b'\x00\x00\x00\x00' + struct.pack('>Q', n)
        return AESGCM(k).encrypt(nonce, plaintext, ad)

    @staticmethod
    def decrypt(k, n, ad, ciphertext):
        nonce = b'\x00\x00\x00\x00' + struct.pack('>Q', n)
        return AESGCM(k).decrypt(nonce, ciphertext, ad)


# ============================================================
# DH Functions (Curve25519)
# ============================================================

DHLEN = 32


def keypair_from_private(private_bytes):
    """Create (private_bytes, public_bytes) from raw Curve25519 private key."""
    public = crypto_scalarmult_base(private_bytes)
    return (private_bytes, public)


def dh(key_pair, public_key):
    """Curve25519 DH: scalar_mult(private, public)."""
    return crypto_scalarmult(key_pair[0], public_key)


# ============================================================
# CipherState
# ============================================================

class CipherState:
    def __init__(self, cipher_cls):
        self.cipher = cipher_cls
        self.k = None
        self.n = 0

    def initialize_key(self, key):
        self.k = key
        self.n = 0

    def has_key(self):
        return self.k is not None

    def encrypt_with_ad(self, ad, plaintext):
        if self.k is not None:
            ct = self.cipher.encrypt(self.k, self.n, ad, plaintext)
            self.n += 1
            return ct
        return plaintext

    def decrypt_with_ad(self, ad, ciphertext):
        if self.k is not None:
            pt = self.cipher.decrypt(self.k, self.n, ad, ciphertext)
            self.n += 1
            return pt
        return ciphertext


# ============================================================
# SymmetricState
# ============================================================

class SymmetricState:
    def __init__(self, cipher_cls, hash_cls):
        self.cs = CipherState(cipher_cls)
        self.hash_cls = hash_cls
        self.ck = None
        self.h = None

    def initialize_symmetric(self, protocol_name_bytes):
        hashlen = self.hash_cls.HASHLEN
        if len(protocol_name_bytes) <= hashlen:
            self.h = protocol_name_bytes + b'\x00' * (hashlen - len(protocol_name_bytes))
        else:
            self.h = self.hash_cls.hash(protocol_name_bytes)
        self.ck = self.h
        self.cs.initialize_key(None)

    def mix_key(self, input_key_material):
        self.ck, temp_k = hkdf(self.hash_cls, self.ck, input_key_material, 2)
        if self.hash_cls.HASHLEN == 64:
            temp_k = temp_k[:32]
        self.cs.initialize_key(temp_k)

    def mix_hash(self, data):
        self.h = self.hash_cls.hash(self.h + data)

    def mix_key_and_hash(self, input_key_material):
        self.ck, temp_h, temp_k = hkdf(self.hash_cls, self.ck, input_key_material, 3)
        self.mix_hash(temp_h)
        if self.hash_cls.HASHLEN == 64:
            temp_k = temp_k[:32]
        self.cs.initialize_key(temp_k)

    def encrypt_and_hash(self, plaintext):
        ciphertext = self.cs.encrypt_with_ad(self.h, plaintext)
        self.mix_hash(ciphertext)
        return ciphertext

    def decrypt_and_hash(self, ciphertext):
        plaintext = self.cs.decrypt_with_ad(self.h, ciphertext)
        self.mix_hash(ciphertext)
        return plaintext

    def split(self):
        temp_k1, temp_k2 = hkdf(self.hash_cls, self.ck, b'', 2)
        if self.hash_cls.HASHLEN == 64:
            temp_k1 = temp_k1[:32]
            temp_k2 = temp_k2[:32]
        c1 = CipherState(self.cs.cipher)
        c2 = CipherState(self.cs.cipher)
        c1.initialize_key(temp_k1)
        c2.initialize_key(temp_k2)
        return c1, c2


# ============================================================
# Handshake Patterns
# ============================================================

# (initiator_pre_message_tokens, responder_pre_message_tokens, [message_patterns])
PATTERNS = {
    'N':  ([], ['s'], [['e', 'es']]),
    'K':  (['s'], ['s'], [['e', 'es', 'ss']]),
    'X':  ([], ['s'], [['e', 'es', 's', 'ss']]),
    'NN': ([], [], [['e'], ['e', 'ee']]),
    'NK': ([], ['s'], [['e', 'es'], ['e', 'ee']]),
    'NX': ([], [], [['e'], ['e', 'ee', 's', 'es']]),
    'KN': (['s'], [], [['e'], ['e', 'ee', 'se']]),
    'KK': (['s'], ['s'], [['e', 'es', 'ss'], ['e', 'ee', 'se']]),
    'KX': (['s'], [], [['e'], ['e', 'ee', 'se', 's', 'es']]),
    'XN': ([], [], [['e'], ['e', 'ee'], ['s', 'se']]),
    'XK': ([], ['s'], [['e', 'es'], ['e', 'ee'], ['s', 'se']]),
    'XX': ([], [], [['e'], ['e', 'ee', 's', 'es'], ['s', 'se']]),
    'IN': ([], [], [['e', 's'], ['e', 'ee', 'se']]),
    'IK': ([], ['s'], [['e', 'es', 's', 'ss'], ['e', 'ee', 'se']]),
    'IX': ([], [], [['e', 's'], ['e', 'ee', 'se', 's', 'es']]),
}


def parse_pattern(pattern_name):
    """Parse a pattern name (possibly with PSK modifiers) into components.

    Returns (init_pre, resp_pre, message_patterns, is_psk).
    """
    # Find where modifiers start (first lowercase letter)
    base = pattern_name
    modifiers = []

    for i, c in enumerate(pattern_name):
        if c.islower():
            base = pattern_name[:i]
            modifier_str = pattern_name[i:]
            modifiers = modifier_str.split('+')
            break

    if base not in PATTERNS:
        raise ValueError(f"Unknown base pattern: {base} (from {pattern_name})")

    init_pre, resp_pre, msgs = PATTERNS[base]
    # Deep copy
    init_pre = list(init_pre)
    resp_pre = list(resp_pre)
    msgs = [list(m) for m in msgs]

    is_psk = False
    for mod in modifiers:
        if mod.startswith('psk'):
            is_psk = True
            psk_index = int(mod[3:])
            if psk_index == 0:
                msgs[0] = ['psk'] + msgs[0]
            else:
                msgs[psk_index - 1] = msgs[psk_index - 1] + ['psk']

    return init_pre, resp_pre, msgs, is_psk


# ============================================================
# HandshakeState
# ============================================================

class HandshakeState:
    def __init__(self, cipher_cls, hash_cls, pattern_name,
                 initiator, s=None, e=None, rs=None, psks=None):
        self.sym = SymmetricState(cipher_cls, hash_cls)
        self.initiator = initiator
        self.s = s      # (private, public) or None
        self.e = e      # (private, public) or None
        self.rs = rs    # public key bytes or None
        self.re = None  # public key bytes or None
        self.is_psk = False
        self.psks = psks or []
        self.psk_idx = 0
        self.message_patterns = []
        self.init_pre = []
        self.resp_pre = []

        init_pre, resp_pre, msgs, is_psk = parse_pattern(pattern_name)
        self.init_pre = init_pre
        self.resp_pre = resp_pre
        self.message_patterns = msgs
        self.is_psk = is_psk

    def initialize(self, protocol_name_str, prologue):
        """Full initialization: symmetric init, prologue, pre-messages."""
        self.sym.initialize_symmetric(protocol_name_str.encode('ascii'))
        self.sym.mix_hash(prologue)

        # Process initiator pre-message public keys
        for token in self.init_pre:
            if token == 'e':
                pk = self.e[1] if self.initiator else self.re
                self.sym.mix_hash(pk)
                if self.is_psk:
                    self.sym.mix_key(pk)
            elif token == 's':
                pk = self.s[1] if self.initiator else self.rs
                self.sym.mix_hash(pk)
                if self.is_psk:
                    self.sym.mix_key(pk)

        # Process responder pre-message public keys
        for token in self.resp_pre:
            if token == 'e':
                pk = self.re if self.initiator else self.e[1]
                self.sym.mix_hash(pk)
                if self.is_psk:
                    self.sym.mix_key(pk)
            elif token == 's':
                pk = self.rs if self.initiator else self.s[1]
                self.sym.mix_hash(pk)
                if self.is_psk:
                    self.sym.mix_key(pk)

    def write_message(self, payload):
        """Send a handshake message. Returns (buffer, split_result_or_None)."""
        pattern = self.message_patterns.pop(0)
        buf = b''

        for token in pattern:
            if token == 'e':
                buf += self.e[1]
                self.sym.mix_hash(self.e[1])
                if self.is_psk:
                    self.sym.mix_key(self.e[1])
            elif token == 's':
                buf += self.sym.encrypt_and_hash(self.s[1])
            elif token == 'ee':
                self.sym.mix_key(dh(self.e, self.re))
            elif token == 'es':
                if self.initiator:
                    self.sym.mix_key(dh(self.e, self.rs))
                else:
                    self.sym.mix_key(dh(self.s, self.re))
            elif token == 'se':
                if self.initiator:
                    self.sym.mix_key(dh(self.s, self.re))
                else:
                    self.sym.mix_key(dh(self.e, self.rs))
            elif token == 'ss':
                self.sym.mix_key(dh(self.s, self.rs))
            elif token == 'psk':
                self.sym.mix_key_and_hash(self.psks[self.psk_idx])
                self.psk_idx += 1

        buf += self.sym.encrypt_and_hash(payload)

        if not self.message_patterns:
            return buf, self.sym.split()
        return buf, None

    def read_message(self, message):
        """Receive a handshake message. Returns (payload, split_result_or_None)."""
        pattern = self.message_patterns.pop(0)
        offset = 0

        for token in pattern:
            if token == 'e':
                self.re = message[offset:offset + DHLEN]
                offset += DHLEN
                self.sym.mix_hash(self.re)
                if self.is_psk:
                    self.sym.mix_key(self.re)
            elif token == 's':
                if self.sym.cs.has_key():
                    length = DHLEN + 16
                else:
                    length = DHLEN
                temp = message[offset:offset + length]
                offset += length
                self.rs = self.sym.decrypt_and_hash(temp)
            elif token == 'ee':
                self.sym.mix_key(dh(self.e, self.re))
            elif token == 'es':
                if self.initiator:
                    self.sym.mix_key(dh(self.e, self.rs))
                else:
                    self.sym.mix_key(dh(self.s, self.re))
            elif token == 'se':
                if self.initiator:
                    self.sym.mix_key(dh(self.s, self.re))
                else:
                    self.sym.mix_key(dh(self.e, self.rs))
            elif token == 'ss':
                self.sym.mix_key(dh(self.s, self.rs))
            elif token == 'psk':
                self.sym.mix_key_and_hash(self.psks[self.psk_idx])
                self.psk_idx += 1

        payload = self.sym.decrypt_and_hash(message[offset:])

        if not self.message_patterns:
            return payload, self.sym.split()
        return payload, None


# ============================================================
# Protocol Name Parsing
# ============================================================

CIPHER_MAP = {'ChaChaPoly': ChaChaPoly, 'AESGCM': AESGCMCipher}
HASH_MAP = {'SHA256': SHA256Hash, 'SHA512': None, 'BLAKE2s': BLAKE2sHash, 'BLAKE2b': BLAKE2bHash}


def parse_protocol_name(name):
    """Parse 'Noise_XX_25519_ChaChaPoly_BLAKE2s' into (pattern, dh, cipher_cls, hash_cls)."""
    parts = name.split('_', 4)
    if len(parts) != 5 or parts[0] != 'Noise':
        raise ValueError(f"Invalid protocol name: {name}")
    pattern = parts[1]
    cipher_cls = CIPHER_MAP[parts[3]]
    hash_cls = HASH_MAP[parts[4]]
    return pattern, parts[2], cipher_cls, hash_cls


# ============================================================
# Session Processing
# ============================================================

def process_session(session):
    """Process one intercepted session, returning handshake_hash and transport payloads."""
    protocol_name = session['protocol_name']
    pattern_name, dh_name, cipher_cls, hash_cls = parse_protocol_name(protocol_name)

    prologue = bytes.fromhex(session['init_prologue'])
    num_hs = session['num_handshake_messages']
    messages = session['messages']

    # Build key pairs from raw private keys
    init_s = keypair_from_private(bytes.fromhex(session['init_static'])) if 'init_static' in session else None
    init_e = keypair_from_private(bytes.fromhex(session['init_ephemeral']))
    resp_s = keypair_from_private(bytes.fromhex(session['resp_static'])) if 'resp_static' in session else None
    resp_e = keypair_from_private(bytes.fromhex(session['resp_ephemeral']))

    init_rs = bytes.fromhex(session['init_remote_static']) if 'init_remote_static' in session else None
    resp_rs = bytes.fromhex(session['resp_remote_static']) if 'resp_remote_static' in session else None

    init_psks = [bytes.fromhex(p) for p in session.get('init_psks', [])]
    resp_psks = [bytes.fromhex(p) for p in session.get('resp_psks', [])]

    # Create both initiator and responder HandshakeStates
    init_hs = HandshakeState(cipher_cls, hash_cls, pattern_name,
                              initiator=True, s=init_s, e=init_e,
                              rs=init_rs, psks=init_psks)
    resp_hs = HandshakeState(cipher_cls, hash_cls, pattern_name,
                              initiator=False, s=resp_s, e=resp_e,
                              rs=resp_rs, psks=resp_psks)

    init_hs.initialize(protocol_name, prologue)
    resp_hs.initialize(protocol_name, prologue)

    # Process handshake messages from both sides
    c1 = c2 = None
    for i in range(num_hs):
        msg = bytes.fromhex(messages[i]['ciphertext'])
        if i % 2 == 0:
            # Initiator sends: responder reads to get payload,
            # then initiator writes with that payload to advance state
            payload, _ = resp_hs.read_message(msg)
            buf, split = init_hs.write_message(payload)
            assert buf == msg, (
                f"Message {i} write mismatch:\n"
                f"  expected: {msg.hex()}\n  got:      {buf.hex()}"
            )
        else:
            # Responder sends: initiator reads to get payload,
            # then responder writes to advance state
            payload, split = init_hs.read_message(msg)
            buf, _ = resp_hs.write_message(payload)
            assert buf == msg, (
                f"Message {i} write mismatch:\n"
                f"  expected: {msg.hex()}\n  got:      {buf.hex()}"
            )

        if split is not None:
            c1, c2 = split

    # Get handshake hash from initiator side
    handshake_hash = init_hs.sym.h.hex()

    # Decrypt transport messages
    transport_payloads = []
    for i in range(num_hs, len(messages)):
        ct = bytes.fromhex(messages[i]['ciphertext'])
        if i % 2 == 0:
            # Initiator sent this message: decrypt with c1
            pt = c1.decrypt_with_ad(b'', ct)
        else:
            # Responder sent this message: decrypt with c2
            pt = c2.decrypt_with_ad(b'', ct)
        transport_payloads.append(pt.hex())

    return {
        'handshake_hash': handshake_hash,
        'transport_payloads': transport_payloads,
    }


def main():
    with open('/app/sessions.json', 'r') as f:
        data = json.load(f)

    results = []
    for idx, session in enumerate(data['sessions']):
        print(f"Processing session {idx}: {session['protocol_name']}")
        result = process_session(session)
        print(f"  handshake_hash: {result['handshake_hash']}")
        print(f"  transport payloads: {len(result['transport_payloads'])}")
        results.append(result)

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nWrote results for {len(results)} sessions to /app/results.json")


if __name__ == '__main__':
    main()
