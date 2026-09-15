"""
TkdbService — Macaroon token verification service.

Implements token issuance, verification with caching, revocation,
service token derivation, and audit logging.

Uses Design C (revocation-first) for cache-consistent revocation.

"""

import os
import sys
import sqlite3
import hmac
import base64

sys.path.insert(0, "/app")
from macaroon import Macaroon, Verifier

from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class TkdbService:

    def __init__(self, db_path, pki_dir):
        self._db_path = db_path
        self._pki_dir = pki_dir
        self._cache = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._master_key = self._derive_master_key()

    # ---- key management ----

    def _derive_master_key(self):
        ca_key_path = os.path.join(self._pki_dir, "ca.key")
        with open(ca_key_path, "rb") as f:
            ca_key = serialization.load_pem_private_key(f.read(), password=None)
        ca_bytes = ca_key.private_numbers().private_value.to_bytes(32, "big")
        hkdf = HKDF(
            algorithm=hashes.SHA256(), length=32,
            salt=b"tkdb-salt-2026", info=b"tkdb-master-key-v1")
        return hkdf.derive(ca_bytes)

    def _get_org_root_key(self, org_name):
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute(
            "SELECT id, encrypted_root_key, nonce FROM organizations WHERE name = ?",
            (org_name,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            raise ValueError(f"Unknown organization: {org_name}")
        org_id, enc_key, nonce = row
        aesgcm = AESGCM(self._master_key)
        root_key = aesgcm.decrypt(nonce, enc_key, None)
        return org_id, root_key

    def _get_org_root_key_by_id(self, org_id):
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute(
            "SELECT name, encrypted_root_key, nonce FROM organizations WHERE id = ?",
            (org_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            raise ValueError(f"Unknown organization id: {org_id}")
        name, enc_key, nonce = row
        aesgcm = AESGCM(self._master_key)
        root_key = aesgcm.decrypt(nonce, enc_key, None)
        return name, root_key

    # ---- database helpers ----

    def _is_blacklisted(self, identifier):
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute(
            "SELECT 1 FROM blacklist WHERE nonce = ?", (identifier,))
        result = cur.fetchone() is not None
        conn.close()
        return result

    def _log(self, operation, token_identifier, org_id=None, result=None):
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT INTO audit_log (operation, token_identifier, org_id, result) "
            "VALUES (?, ?, ?, ?)",
            (operation, token_identifier, org_id, result))
        conn.commit()
        conn.close()

    # ---- public API ----

    def issue(self, org_name, caveats=None):
        org_id, root_key = self._get_org_root_key(org_name)
        random_hex = os.urandom(16).hex()
        identifier = f"org:{org_id}:{random_hex}"
        m = Macaroon(location="https://tkdb.internal",
                     identifier=identifier, key=root_key)
        if caveats:
            for c in caveats:
                m = m.add_first_party_caveat(c)
        token_b64 = base64.b64encode(m.serialize()).decode("ascii")
        self._log("issue", identifier, org_id, "success")
        return {"token": token_b64, "identifier": identifier}

    def verify(self, token_b64, satisfiers=None):
        data = base64.b64decode(token_b64)
        m = Macaroon.deserialize(data)
        identifier = m.identifier
        parts = identifier.split(":")
        try:
            org_id = int(parts[1])
        except (ValueError, IndexError):
            self._log("verify", identifier, None, "bad_identifier")
            return {"valid": False, "identifier": identifier, "cached": False}

        # --- Design C: revocation-first with cache fallthrough ---
        # ALWAYS check revocation before cache lookup
        if self._is_blacklisted(identifier):
            self._cache.pop(m.signature, None)
            self._log("verify", identifier, org_id, "revoked")
            return {"valid": False, "identifier": identifier, "cached": False}

        # Then check cache
        cache_key = m.signature
        if cache_key in self._cache:
            self._cache_hits += 1
            self._log("verify", identifier, org_id, "cached")
            return {"valid": self._cache[cache_key],
                    "identifier": identifier, "cached": True}

        # Cache miss: full verification
        self._cache_misses += 1
        try:
            _, root_key = self._get_org_root_key_by_id(org_id)
        except ValueError:
            self._log("verify", identifier, org_id, "unknown_org")
            return {"valid": False, "identifier": identifier, "cached": False}

        v = Verifier()
        if satisfiers:
            for s in satisfiers:
                v.satisfy_exact(s)

        valid = v.verify(m, root_key)
        self._cache[cache_key] = valid
        self._log("verify", identifier, org_id, "valid" if valid else "invalid")
        return {"valid": valid, "identifier": identifier, "cached": False}

    def revoke(self, identifier):
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT OR IGNORE INTO blacklist (nonce) VALUES (?)",
            (identifier,))
        conn.commit()
        conn.close()
        self._log("revoke", identifier, result="success")
        return {"revoked": True, "identifier": identifier}

    def derive_service_token(self, token_b64, strip_predicates=None):
        data = base64.b64decode(token_b64)
        m = Macaroon.deserialize(data)
        identifier = m.identifier
        org_id = int(identifier.split(":")[1])
        _, root_key = self._get_org_root_key_by_id(org_id)

        # Verify original token with permissive satisfiers
        v = Verifier()
        v.satisfy_general(lambda _: True)
        if not v.verify(m, root_key):
            raise ValueError("Cannot derive service token from invalid token")

        # Create new service token
        random_hex = os.urandom(16).hex()
        new_identifier = f"svc:{org_id}:{random_hex}"
        new_mac = Macaroon(location="https://tkdb.internal",
                           identifier=new_identifier, key=root_key)
        strip = strip_predicates or []
        for cav in m.caveats:
            if "vid" in cav:
                continue
            pred = cav["cid"]
            if any(pred.startswith(sp) for sp in strip):
                continue
            new_mac = new_mac.add_first_party_caveat(pred)

        token_b64_out = base64.b64encode(new_mac.serialize()).decode("ascii")
        self._log("derive", new_identifier, org_id, "success")
        return {"token": token_b64_out, "identifier": new_identifier}

    def get_revocations(self, since=None):
        conn = sqlite3.connect(self._db_path)
        if since:
            cur = conn.execute(
                "SELECT nonce, created_at FROM blacklist "
                "WHERE created_at > ? ORDER BY created_at", (since,))
        else:
            cur = conn.execute(
                "SELECT nonce, created_at FROM blacklist ORDER BY created_at")
        result = [{"identifier": row[0], "revoked_at": row[1]}
                  for row in cur.fetchall()]
        conn.close()
        return result

    def cache_stats(self):
        return {
            "size": len(self._cache),
            "hits": self._cache_hits,
            "misses": self._cache_misses,
        }
