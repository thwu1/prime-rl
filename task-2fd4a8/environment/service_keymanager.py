"""Key management for the data encryption service."""
import hmac
import hashlib
import json

SALT = b"xaes-audit-service-v1"


def hkdf_sha256(ikm, salt, info, length=32):
    """HKDF-SHA256 key derivation (extract-then-expand)."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    t = b""
    okm = b""
    for i in range(1, (length + 31) // 32 + 1):
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def derive_record_key(master_key, record_id):
    """Derive a per-record 256-bit encryption key from the master key."""
    return hkdf_sha256(master_key, SALT, record_id.encode())


def load_master_key(config_path="/app/service/config.json"):
    """Load the master key from the service configuration."""
    with open(config_path) as f:
        config = json.load(f)
    return bytes.fromhex(config["master_key_hex"])
