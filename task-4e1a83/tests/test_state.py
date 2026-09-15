
import base64
import hashlib
import os
import sqlite3
import struct


# ---------- PEM / ASN.1 DER helpers ----------

def _parse_der_length(data, offset):
    if data[offset] < 0x80:
        return data[offset], offset + 1
    num_bytes = data[offset] & 0x7F
    length = int.from_bytes(data[offset + 1:offset + 1 + num_bytes], "big")
    return length, offset + 1 + num_bytes


def _parse_der_integer(data, offset):
    assert data[offset] == 0x02, "Expected INTEGER tag"
    length, offset = _parse_der_length(data, offset + 1)
    value = int.from_bytes(data[offset:offset + length], "big")
    return value, offset + length


def parse_dh_pem(filepath):
    """Extract modulus and generator from a DH parameters PEM file."""
    with open(filepath) as f:
        pem = f.read()
    b64_lines = [
        line for line in pem.strip().split("\n")
        if not line.startswith("-----")
    ]
    der = base64.b64decode("".join(b64_lines))
    assert der[0] == 0x30, "Expected SEQUENCE tag"
    _, offset = _parse_der_length(der, 1)
    modulus, offset = _parse_der_integer(der, offset)
    generator, offset = _parse_der_integer(der, offset)
    return modulus, generator


def parse_binary_capture(filepath):
    """Parse the proprietary binary session capture file."""
    with open(filepath, "rb") as f:
        data = f.read()
    assert data[0:4] == b"KSEC", "Bad magic"
    offset = 6  # skip magic(4) + version(2)
    offset += 8  # skip timestamp
    sid_len = data[offset]
    offset += 1
    session_id = data[offset:offset + sid_len].decode("ascii")
    offset += sid_len
    offset += 1  # skip cipher suite byte
    payload_len = struct.unpack(">I", data[offset:offset + 4])[0]
    offset += 4
    ciphertext = data[offset:offset + payload_len]
    offset += payload_len
    plaintext_hash = data[offset:offset + 32]
    return session_id, ciphertext, plaintext_hash


def get_public_key_from_db(db_path, session_id):
    """Query the audit database for the public key of a session."""
    db = sqlite3.connect(db_path)
    cur = db.cursor()
    cur.execute(
        "SELECT public_value_hex FROM key_exchanges WHERE session_id = ?",
        (session_id,),
    )
    row = cur.fetchone()
    db.close()
    assert row is not None, f"Session {session_id} not found in audit.db"
    return int(row[0], 16)


# ---------- Load everything from artifacts ----------

PEM_PATH = "/app/artifacts/server_dhparams.pem"
DB_PATH = "/app/artifacts/audit.db"
BIN_PATH = "/app/artifacts/session_capture.bin"


class TestPrivateKeyRecovery:
    """Verify the agent recovered the correct DH private key."""

    def test_private_key_file_exists(self):
        assert os.path.isfile("/app/private_key.txt"), (
            "private_key.txt not found in /app/"
        )

    def test_private_key_is_integer(self):
        with open("/app/private_key.txt") as f:
            content = f.read().strip()
        a = int(content)
        assert a > 1, "Private key must be > 1"

    def test_private_key_satisfies_dlog(self):
        """Core verification: g^a == A (mod n)."""
        n, g = parse_dh_pem(PEM_PATH)
        session_id, _, _ = parse_binary_capture(BIN_PATH)
        A = get_public_key_from_db(DB_PATH, session_id)

        with open("/app/private_key.txt") as f:
            a = int(f.read().strip())

        computed_A = pow(g, a, n)
        assert computed_A == A, (
            f"Discrete log verification failed: "
            f"g^a mod n = {computed_A}, expected A = {A}"
        )


class TestDecryption:
    """Verify the agent correctly decrypted the message."""

    def test_decrypted_file_exists(self):
        assert os.path.isfile("/app/decrypted.txt"), (
            "decrypted.txt not found in /app/"
        )

    def test_decrypted_matches_plaintext_hash(self):
        """Verify decrypted text hashes to the value embedded in the capture."""
        _, _, expected_hash = parse_binary_capture(BIN_PATH)

        with open("/app/decrypted.txt") as f:
            plaintext = f.read().strip()

        actual_hash = hashlib.sha256(plaintext.encode("utf-8")).digest()
        assert actual_hash == expected_hash, (
            "SHA-256 of decrypted text does not match the hash in the capture"
        )

    def test_decrypted_consistent_with_key(self):
        """Verify decrypted text is consistent with the recovered key."""
        _, ciphertext, _ = parse_binary_capture(BIN_PATH)

        with open("/app/private_key.txt") as f:
            a = int(f.read().strip())

        key = hashlib.sha256(str(a).encode()).digest()
        expected = bytes(
            ciphertext[i] ^ key[i % 32] for i in range(len(ciphertext))
        )

        with open("/app/decrypted.txt") as f:
            actual = f.read().strip()

        assert actual == expected.decode("utf-8", errors="replace").strip(), (
            "Decrypted text does not match XOR decryption with recovered key"
        )

    def test_modulus_is_not_prime(self):
        """Sanity: the modulus should not be prime (Fermat check)."""
        n, _ = parse_dh_pem(PEM_PATH)
        fermat = pow(2, n - 1, n)
        assert fermat != 1, (
            "Modulus appears prime but should not be for this challenge"
        )
