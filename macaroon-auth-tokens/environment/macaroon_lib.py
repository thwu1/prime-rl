"""
Macaroon authorization token library.
Production-grade implementation for use with tkdb service.

Provides: Macaroon, Verifier, ThirdPartyDischarger, RevocationStore

"""

import hmac as _hmac
import hashlib as _hashlib
import os as _os

import msgpack as _msgpack
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305 as _ChaCha


def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    return _hmac.new(key, data, _hashlib.sha256).digest()


def _aead_encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = _os.urandom(12)
    ct = _ChaCha(key).encrypt(nonce, plaintext, None)
    return nonce + ct


def _aead_decrypt(key: bytes, data: bytes) -> bytes:
    return _ChaCha(key).decrypt(data[:12], data[12:], None)


class Macaroon:
    def __init__(self, location: str, identifier: str, key: bytes = None,
                 *, _signature: bytes = None, _caveats: list = None):
        self._location = location
        self._identifier = identifier
        if key is not None:
            self._signature = _hmac_sha256(key, identifier.encode("utf-8"))
        elif _signature is not None:
            self._signature = _signature
        else:
            raise ValueError("Provide either key or _signature")
        self._caveats = list(_caveats) if _caveats is not None else []

    @property
    def location(self) -> str:
        return self._location

    @property
    def identifier(self) -> str:
        return self._identifier

    @property
    def signature(self) -> bytes:
        return self._signature

    @property
    def caveats(self) -> list:
        return self._caveats

    def add_first_party_caveat(self, predicate: str) -> "Macaroon":
        if not predicate:
            raise ValueError("Caveat predicate must not be empty")
        new_sig = _hmac_sha256(self._signature, predicate.encode("utf-8"))
        new_cavs = [c.copy() for c in self._caveats] + [{"cid": predicate}]
        return Macaroon(self._location, self._identifier,
                        _signature=new_sig, _caveats=new_cavs)

    def add_third_party_caveat(self, location: str, key: bytes,
                               identifier: str) -> "Macaroon":
        crk = _os.urandom(32)
        vid = _aead_encrypt(self._signature, crk)
        ticket = _aead_encrypt(key, crk)
        new_sig = _hmac_sha256(self._signature,
                               vid + identifier.encode("utf-8"))
        cav = {"cid": identifier, "vid": vid, "cl": location, "ticket": ticket}
        new_cavs = [c.copy() for c in self._caveats] + [cav]
        return Macaroon(self._location, self._identifier,
                        _signature=new_sig, _caveats=new_cavs)

    def prepare_for_request(self, root_signature: bytes) -> "Macaroon":
        bound = _hmac_sha256(root_signature, self._signature)
        return Macaroon(self._location, self._identifier,
                        _signature=bound,
                        _caveats=[c.copy() for c in self._caveats])

    def serialize(self) -> bytes:
        return _msgpack.packb({
            "location": self._location,
            "identifier": self._identifier,
            "caveats": self._caveats,
            "signature": self._signature,
        }, use_bin_type=True)

    @classmethod
    def deserialize(cls, data: bytes) -> "Macaroon":
        d = _msgpack.unpackb(data, raw=False)
        cavs = []
        for c in d["caveats"]:
            out = {}
            for k, v in c.items():
                k = k.decode("utf-8") if isinstance(k, bytes) else k
                if k in ("cid", "cl") and isinstance(v, bytes):
                    v = v.decode("utf-8")
                out[k] = v
            cavs.append(out)
        loc = d["location"]
        if isinstance(loc, bytes):
            loc = loc.decode("utf-8")
        ident = d["identifier"]
        if isinstance(ident, bytes):
            ident = ident.decode("utf-8")
        return cls(loc, ident, _signature=d["signature"], _caveats=cavs)


class Verifier:
    def __init__(self):
        self._exact = set()
        self._general = []

    def satisfy_exact(self, predicate: str):
        self._exact.add(predicate)

    def satisfy_general(self, func):
        self._general.append(func)

    def _check(self, predicate: str) -> bool:
        if predicate in self._exact:
            return True
        return any(f(predicate) for f in self._general)

    def verify(self, macaroon, key: bytes, discharge_macaroons=None) -> bool:
        discharges = discharge_macaroons or []
        sig = _hmac_sha256(key, macaroon.identifier.encode("utf-8"))
        tp_list = []
        for cav in macaroon.caveats:
            if "vid" in cav:
                try:
                    crk = _aead_decrypt(sig, cav["vid"])
                except Exception:
                    return False
                tp_list.append((crk, cav["cid"]))
                sig = _hmac_sha256(sig, cav["vid"] + cav["cid"].encode("utf-8"))
            else:
                if not self._check(cav["cid"]):
                    return False
                sig = _hmac_sha256(sig, cav["cid"].encode("utf-8"))
        if not _hmac.compare_digest(sig, macaroon.signature):
            return False
        for crk, cid in tp_list:
            dm = None
            for d in discharges:
                if d.identifier == cid:
                    dm = d
                    break
            if dm is None:
                return False
            if not self._verify_discharge(dm, crk, macaroon.signature):
                return False
        return True

    def _verify_discharge(self, discharge, crk: bytes,
                          root_sig: bytes) -> bool:
        d_sig = _hmac_sha256(crk, discharge.identifier.encode("utf-8"))
        for cav in discharge.caveats:
            if "vid" in cav:
                return False
            if not self._check(cav["cid"]):
                return False
            d_sig = _hmac_sha256(d_sig, cav["cid"].encode("utf-8"))
        expected = _hmac_sha256(root_sig, d_sig)
        return _hmac.compare_digest(expected, discharge.signature)


class ThirdPartyDischarger:
    def __init__(self, key: bytes):
        self._key = key

    def discharge(self, caveat: dict, location: str) -> Macaroon:
        crk = _aead_decrypt(self._key, caveat["ticket"])
        return Macaroon(location=location, identifier=caveat["cid"], key=crk)


class RevocationStore:
    def __init__(self):
        self._revoked = set()

    def revoke(self, identifier: str):
        self._revoked.add(identifier)

    def is_revoked(self, identifier: str) -> bool:
        return identifier in self._revoked
