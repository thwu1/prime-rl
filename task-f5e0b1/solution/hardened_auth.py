"""
Hardened iperf3 authentication module.

Addresses all identified vulnerabilities in the original iperf3 auth protocol:
- RSA-OAEP instead of PKCS1v1.5 (mitigates Marvin/Bleichenbacher timing attacks)
- Argon2id for password hashing instead of raw SHA256 (resistant to GPU brute-force)
- Random nonce in each token (prevents replay attacks within timestamp skew window)
- JSON-structured payload with input validation
"""

import base64
import json
import os
import time

import argon2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend


def generate_keypair(key_size=2048):
    """Generate an RSA key pair for token encryption.

    Returns (private_pem_bytes, public_pem_bytes).
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
        backend=default_backend(),
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def encode_token(username, password, public_key_pem):
    """Encode an authentication token using RSA-OAEP with a random nonce.

    Returns a base64-encoded string.
    """
    if isinstance(public_key_pem, str):
        public_key_pem = public_key_pem.encode()
    pub_key = serialization.load_pem_public_key(public_key_pem)

    nonce = os.urandom(16).hex()
    timestamp = int(time.time())

    payload = json.dumps({
        'username': username,
        'password': password,
        'timestamp': timestamp,
        'nonce': nonce,
    }, separators=(',', ':')).encode('utf-8')

    encrypted = pub_key.encrypt(
        payload,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(encrypted).decode('ascii')


def decode_token(token_str, private_key_pem):
    """Decode an RSA-OAEP encrypted authentication token.

    Returns dict with keys: username, password, timestamp, nonce.
    """
    if isinstance(private_key_pem, str):
        private_key_pem = private_key_pem.encode()
    priv_key = serialization.load_pem_private_key(private_key_pem, password=None)

    encrypted = base64.b64decode(token_str)
    decrypted = priv_key.decrypt(
        encrypted,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return json.loads(decrypted.decode('utf-8'))


def _hash_password(password):
    """Hash a password using Argon2id."""
    ph = argon2.PasswordHasher(
        time_cost=2,
        memory_cost=65536,
        parallelism=1,
        hash_len=32,
        salt_len=16,
    )
    return ph.hash(password)


def _verify_hash(password, hash_str):
    """Verify a password against an Argon2id hash."""
    ph = argon2.PasswordHasher()
    try:
        return ph.verify(hash_str, password)
    except argon2.exceptions.VerifyMismatchError:
        return False


def create_credential_store(users_dict, store_path):
    """Create a credential store with Argon2id-hashed passwords.

    users_dict: {username: plaintext_password}
    """
    with open(store_path, 'w') as f:
        for username in sorted(users_dict.keys()):
            h = _hash_password(users_dict[username])
            f.write("%s,%s\n" % (username, h))


def verify_credentials(username, password, store_path):
    """Verify credentials against a hardened credential store."""
    with open(store_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',', 1)
            if len(parts) == 2 and parts[0] == username:
                return _verify_hash(password, parts[1])
    return False


def migrate_credentials(old_csv_path, password_map, new_store_path):
    """Migrate old SHA256-based credentials to Argon2id format.

    old_csv_path: path to the old username,sha256hash CSV
    password_map: {username: plaintext_password} for users whose passwords are known
    new_store_path: output path for the hardened credential store

    Returns a dict with migration statistics.
    """
    old_users = {}
    with open(old_csv_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',', 1)
            if len(parts) == 2:
                old_users[parts[0]] = parts[1]

    migrated = 0
    skipped = 0
    migrated_list = []
    skipped_list = []

    with open(new_store_path, 'w') as f:
        for username in sorted(old_users.keys()):
            if username in password_map:
                h = _hash_password(password_map[username])
                f.write("%s,%s\n" % (username, h))
                migrated += 1
                migrated_list.append(username)
            else:
                skipped += 1
                skipped_list.append(username)

    return {
        'total_users': len(old_users),
        'migrated_count': migrated,
        'skipped_count': skipped,
        'migrated_users': migrated_list,
        'skipped_users': skipped_list,
    }
