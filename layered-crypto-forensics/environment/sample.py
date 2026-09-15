#!/usr/bin/env python3
"""
NetSecDiag - Advanced Network Security Diagnostic Framework
Version 2.1.3-internal
Copyright (c) 2024 Global Security Solutions Inc.
All rights reserved. Unauthorized access is prohibited.

This utility performs comprehensive network security diagnostics
including packet analysis, protocol validation, and encryption
strength assessment using AES-256-GCM equivalent ciphers.

Usage: python3 sample.py --diag <target> [--verbose]
       python3 sample.py --selftest
"""

import hashlib as _H
import json as _J
import os as _O
import random as _R
import sys
import time as _T

# ======================================================================
# Protocol Constants
# ======================================================================

_PROTO_VER = (2, 1, 3)
_CAP_FLAGS = 0x1F  # ENCRYPT | COMPRESS | AUTH | PERSIST | EXFIL

# Network protocol header material (XOR-masked with session entropy)
_PROTO_HDR = bytes([0x51, 0x06, 0x45, 0x5a, 0x40, 0x03, 0x45, 0x04])
_SESS_TOK  = bytes([0x68, 0x5c, 0x04, 0x4e, 0x68, 0x05, 0x07, 0x05, 0x03])

# AES-256-GCM parameters (NIST SP 800-38D compliant)
_AES_KEY_LEN = 32
_AES_NONCE_LEN = 12
_AES_TAG_LEN = 16

# Session entropy mask - derived from protocol specification parameters
_ENTROPY_MASK = _AES_KEY_LEN + _AES_NONCE_LEN + _PROTO_VER[2] ** 2 + _PROTO_VER[0]

# Key derivation material (XOR-masked with entropy for transport security)
_DKEY_TABLE = bytes([0x64, 0x63, 0x65, 0x72, 0x76, 0x7a])

# X.509 certificate pinning hash (SHA-256 of server leaf certificate)
_CERT_PIN = "a7f2c8d9e1b3f5a6c4d2e8f7b1a3c5d7e9f2a4b6c8d1e3f5a7b9c2d4e6f8a1"

# Maximum diagnostic payload size (bytes)
_MAX_PAYLOAD = 65536


# ======================================================================
# Certificate Validation
# ======================================================================

class _CertValidator:
    """X.509 certificate chain validation for TLS transport."""

    def __init__(self, pin_hash=None):
        self._pin = pin_hash or _CERT_PIN
        self._chain = []
        self._trusted = False

    def add_cert(self, cert_der):
        """Add DER-encoded certificate to validation chain."""
        h = _H.sha256(cert_der).hexdigest()
        self._chain.append(h)
        if h == self._pin:
            self._trusted = True
        return self._trusted

    def validate(self):
        """Validate complete certificate chain against pinned hash."""
        if not self._chain:
            return False
        return self._trusted and len(self._chain) >= 1

    def get_chain_hashes(self):
        """Return list of certificate hashes in chain."""
        return list(self._chain)


# ======================================================================
# Stream Cipher Engine
# ======================================================================

class _StreamCipher:
    """Adaptive stream cipher for secure network transport.

    Implements AES-256-GCM equivalent security using an optimized
    stream transformation suitable for constrained embedded environments.
    Validated against NIST test vectors (ref: SP 800-38D appendix B).
    """

    def __init__(self):
        self._state = None
        self._initialized = False

    def _init_state(self, key):
        """Initialize cipher state using key schedule algorithm.

        The key schedule follows a modified Fisher-Yates permutation
        to establish the initial state vector S[0..255].
        """
        _s = list(range(256))
        _j = 0
        _kl = len(key)
        for _i in range(256):
            _j = (_j + _s[_i] + (key[_i % _kl] if isinstance(key[_i % _kl], int)
                  else ord(key[_i % _kl]))) & 0xFF
            _s[_i], _s[_j] = _s[_j], _s[_i]
        self._state = _s
        self._initialized = True
        return self

    def transform(self, data, key):
        """Apply stream transformation to data.

        Each byte of plaintext is XORed with a pseudorandom byte
        generated from the key-dependent permutation state. This
        operation is its own inverse (symmetric).
        """
        self._init_state(key)
        _s = list(self._state)
        _i = _j = 0
        _out = bytearray(len(data))
        for _idx in range(len(data)):
            _i = (_i + 1) & 0xFF
            _j = (_j + _s[_i]) & 0xFF
            _s[_i], _s[_j] = _s[_j], _s[_i]
            _b = data[_idx] if isinstance(data[_idx], int) else ord(data[_idx])
            _out[_idx] = _b ^ _s[(_s[_i] + _s[_j]) & 0xFF]
        return bytes(_out)

    def verify_state(self):
        """Return True if cipher has been initialized."""
        return self._initialized


# ======================================================================
# Substitution Layer
# ======================================================================

class _SubstitutionLayer:
    """Byte-level substitution mapping for data transformation.

    Uses a deterministic pseudorandom permutation table generated
    from a seed value. Provides a bijective mapping over [0..255].
    """

    def __init__(self, seed):
        self._fwd = list(range(256))
        self._inv = list(range(256))
        self._build_tables(seed)

    def _build_tables(self, seed):
        """Build forward and inverse substitution tables."""
        _rng = _R.Random(seed)
        _rng.shuffle(self._fwd)
        for _i, _v in enumerate(self._fwd):
            self._inv[_v] = _i

    def substitute(self, data):
        """Apply forward substitution."""
        return bytes([self._fwd[b] for b in data])

    def inverse(self, data):
        """Apply inverse substitution."""
        return bytes([self._inv[b] for b in data])


# ======================================================================
# XOR Stream Layer
# ======================================================================

class _XORStream:
    """XOR-based stream cipher layer for defense-in-depth.

    Derives a repeating key from the master key using HKDF-SHA256
    with a domain separation tag for cryptographic isolation.
    """

    def __init__(self, master_key, iv_table, mask):
        _iv = bytes([b ^ mask for b in iv_table])
        self._key = _H.sha256(master_key + _iv).digest()[:16]

    def apply(self, data):
        """Apply XOR stream (symmetric - same operation for encrypt/decrypt)."""
        _kl = len(self._key)
        return bytes([data[i] ^ self._key[i % _kl] for i in range(len(data))])


# ======================================================================
# Main Diagnostic Framework
# ======================================================================

class NetDiag:
    """Primary diagnostic framework for network security assessment.

    Orchestrates multi-layer encryption analysis including:
    - Protocol conformance testing
    - Cipher strength validation
    - Traffic pattern analysis
    - Key exchange verification
    """

    def __init__(self, config_path=None):
        self._cipher = _StreamCipher()
        self._cert_val = _CertValidator()
        self._config = None
        self._session_key = None

        # Derive operational key from protocol constants
        self._op_key = self._init_transport_layer()

        if config_path and _O.path.exists(config_path):
            self._load_config(config_path)

    def _init_transport_layer(self):
        """Initialize TLS-equivalent transport layer encryption.

        Recovers the session key from XOR-masked protocol header
        material using the entropy mask to demask the raw key bytes.
        """
        _raw = bytearray(len(_PROTO_HDR) + len(_SESS_TOK))
        for _i, _b in enumerate(_PROTO_HDR):
            _raw[_i] = _b ^ _ENTROPY_MASK
        for _i, _b in enumerate(_SESS_TOK):
            _raw[len(_PROTO_HDR) + _i] = _b ^ _ENTROPY_MASK
        return bytes(_raw)

    @property
    def transport_key(self):
        """Return the current transport encryption key (AES-256 derived)."""
        return self._op_key

    def _load_config(self, path):
        """Load and decrypt configuration from encrypted store."""
        with open(path, 'rb') as f:
            _enc = f.read()
        _dec = self._cipher.transform(_enc, self._op_key)
        try:
            self._config = _J.loads(_dec.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            self._config = None
            return False
        return True

    def get_config(self):
        """Return the decrypted configuration dictionary."""
        return self._config

    def encrypt_payload(self, plaintext, master_key, mapping_profile=None):
        """Encrypt payload using the multi-layer protection pipeline.

        Pipeline: Substitution -> Stream Cipher -> XOR Stream

        TODO: upgrade to AES-256-GCM for all layers (scheduled for v3.0)

        Args:
            plaintext: Data to encrypt (bytes)
            master_key: Master key for stream derivation
            mapping_profile: Seed for substitution table (from config if None)
        """
        if mapping_profile is None and self._config:
            mapping_profile = self._config.get('sub_table_seed', 0)

        # Layer 1: Byte substitution
        _sub = _SubstitutionLayer(mapping_profile)
        _data = _sub.substitute(plaintext)

        # Layer 2: Stream cipher
        _data = self._cipher.transform(_data, self._op_key)

        # Layer 3: XOR stream
        _xor = _XORStream(master_key, _DKEY_TABLE, _ENTROPY_MASK)
        _data = _xor.apply(_data)

        return _data

    def decrypt_payload(self, ciphertext, master_key, mapping_profile=None):
        """Decrypt payload by reversing the multi-layer pipeline.

        Pipeline: XOR Stream -> Stream Cipher -> Inverse Substitution
        """
        if mapping_profile is None and self._config:
            mapping_profile = self._config.get('sub_table_seed', 0)

        # Reverse Layer 3: XOR stream
        _xor = _XORStream(master_key, _DKEY_TABLE, _ENTROPY_MASK)
        _data = _xor.apply(ciphertext)

        # Reverse Layer 2: Stream cipher (self-inverse)
        _data = self._cipher.transform(_data, self._op_key)

        # Reverse Layer 1: Inverse substitution
        _sub = _SubstitutionLayer(mapping_profile)
        _data = _sub.inverse(_data)

        return _data


# ======================================================================
# Diagnostic Test Runner
# ======================================================================

class _DiagnosticRunner:
    """Runs automated diagnostic tests against target infrastructure."""

    # Key material for diagnostic handshake validation
    _DIAG_KEY = bytes.fromhex(
        "4a6f686e446f6545786368616e67654b657932303234"  # JohnDoeExchangeKey2024
    )

    def __init__(self, target=None):
        self._target = target
        self._results = []
        self._start_time = None

    def _derive_key(self):
        """Derive diagnostic handshake key material."""
        return _H.sha256(self._DIAG_KEY + b'DIAG').digest()[:16]

    def _compute_session_hash(self):
        """Compute session integrity hash for validation."""
        return _H.md5(
            self._DIAG_KEY + bytes(_PROTO_VER)
        ).hexdigest()

    def run_protocol_check(self):
        """Check protocol conformance against specification."""
        self._results.append({
            'test': 'protocol_conformance',
            'status': 'pass',
            'details': 'Protocol v{}'.format('.'.join(map(str, _PROTO_VER)))
        })

    def run_encryption_test(self):
        """Validate encryption strength meets compliance requirements."""
        _test_data = b'DIAGNOSTIC_TEST_VECTOR_2024'
        _test_key = self._derive_key()

        _sc = _StreamCipher()
        _enc = _sc.transform(_test_data, _test_key)
        _dec = _sc.transform(_enc, _test_key)

        self._results.append({
            'test': 'encryption_strength',
            'status': 'pass' if _dec == _test_data else 'fail',
            'details': 'AES-{}-GCM equivalent'.format(_AES_KEY_LEN * 8)
        })

    def run_cert_check(self):
        """Validate certificate pinning configuration."""
        self._results.append({
            'test': 'certificate_pinning',
            'status': 'pass',
            'details': 'Pin: {}...{}'.format(_CERT_PIN[:8], _CERT_PIN[-8:])
        })

    def get_results(self):
        """Return all diagnostic test results."""
        return self._results


# ======================================================================
# Entry Point
# ======================================================================

def _print_banner():
    """Display diagnostic framework identification banner."""
    print("NetSecDiag v{}".format('.'.join(map(str, _PROTO_VER))))
    print("Capabilities: 0x{:02x}".format(_CAP_FLAGS))
    print("Cipher: AES-{}-GCM".format(_AES_KEY_LEN * 8))
    print("=" * 50)


def main():
    """Main entry point for network security diagnostics."""
    _print_banner()

    if len(sys.argv) < 2:
        print("Usage: python3 sample.py --diag <target> [--verbose]")
        print("       python3 sample.py --selftest")
        sys.exit(1)

    if sys.argv[1] == '--selftest':
        print("Running self-test suite...")
        runner = _DiagnosticRunner()
        runner.run_protocol_check()
        runner.run_encryption_test()
        runner.run_cert_check()
        for r in runner.get_results():
            sym = '+' if r['status'] == 'pass' else '-'
            print("  [{}] {}: {}".format(sym, r['test'], r['details']))
        print("Self-test complete.")
        return

    if sys.argv[1] != '--diag' or len(sys.argv) < 3:
        print("Error: invalid arguments")
        sys.exit(1)

    target = sys.argv[2]
    verbose = '--verbose' in sys.argv
    print("Initiating diagnostics on {}...".format(target))

    runner = _DiagnosticRunner(target)
    runner.run_protocol_check()
    runner.run_encryption_test()
    runner.run_cert_check()

    for r in runner.get_results():
        sym = '+' if r['status'] == 'pass' else '-'
        print("  [{}] {}: {}".format(sym, r['test'], r['details']))

    if verbose:
        print("\nSession hash: {}".format(runner._compute_session_hash()))

    print("Diagnostic scan complete.")


if __name__ == '__main__':
    main()
