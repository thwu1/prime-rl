#!/usr/bin/env python3
"""
Plausibly Deniable Database (PDDB) — Encrypted key-value store with
multi-basis overlay semantics and plausible deniability.
"""

import os
import json
import hmac
import hashlib

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes


class PDDB:
    NONCE_SIZE = 12
    TAG_SIZE = 16
    MAX_PROBE = 32
    PT_MAGIC = "PDDB_PT"

    def __init__(self, image_path: str, num_pages: int = 256, page_size: int = 4096):
        self.image_path = image_path
        self.num_pages = num_pages
        self.page_size = page_size
        self.payload_size = page_size - self.NONCE_SIZE - self.TAG_SIZE

        # In-memory state for unlocked bases
        self._basis_keys: dict[str, bytes] = {}
        self._basis_pt_page: dict[str, int] = {}
        self._basis_entries: dict[str, dict] = {}
        self._unlock_order: list[str] = []

        if os.path.exists(image_path):
            with open(image_path, 'rb') as f:
                self._image = bytearray(f.read())
            expected = num_pages * page_size
            if len(self._image) != expected:
                raise ValueError(
                    f"Image size {len(self._image)} != expected {expected}"
                )
        else:
            self._image = None

    # ------------------------------------------------------------------
    # Low-level page I/O
    # ------------------------------------------------------------------

    def _read_page(self, idx: int) -> bytes:
        off = idx * self.page_size
        return bytes(self._image[off:off + self.page_size])

    def _write_page(self, idx: int, data: bytes) -> None:
        assert len(data) == self.page_size
        off = idx * self.page_size
        self._image[off:off + self.page_size] = data

    # ------------------------------------------------------------------
    # Cryptography helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_key(name: str, password: str) -> bytes:
        """Deterministic 32-byte AES key from (name, password) via HMAC."""
        prk = hmac.new(
            name.encode('utf-8'), password.encode('utf-8'), hashlib.sha256
        ).digest()
        okm = hmac.new(prk, b"pddb-basis-key\x01", hashlib.sha256).digest()
        return okm

    def _derive_pt_location(self, key: bytes) -> int:
        """Deterministic page-table page index from basis key."""
        h = hmac.new(key, b"pddb-pt-location", hashlib.sha256).digest()
        return int.from_bytes(h[:4], 'big') % self.num_pages

    def _encrypt(self, key: bytes, plaintext: bytes) -> bytes:
        """Encrypt plaintext, pad to payload_size, return page_size bytes."""
        if len(plaintext) > self.payload_size:
            raise ValueError("Plaintext exceeds page payload capacity")
        padded = plaintext + b'\x00' * (self.payload_size - len(plaintext))
        nonce = hashlib.sha256(padded).digest()[:self.NONCE_SIZE]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ct, tag = cipher.encrypt_and_digest(padded)
        return nonce + ct + tag

    def _encrypt_raw(self, key: bytes, padded_plaintext: bytes) -> bytes:
        """Encrypt already-padded plaintext (exactly payload_size bytes)."""
        assert len(padded_plaintext) == self.payload_size
        nonce = hashlib.sha256(padded_plaintext).digest()[:self.NONCE_SIZE]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ct, tag = cipher.encrypt_and_digest(padded_plaintext)
        return nonce + ct + tag

    def _decrypt(self, key: bytes, page_data: bytes):
        """Decrypt page_data -> padded plaintext or None on auth failure."""
        if len(page_data) != self.page_size:
            return None
        nonce = page_data[:self.NONCE_SIZE]
        ct = page_data[self.NONCE_SIZE:-self.TAG_SIZE]
        tag = page_data[-self.TAG_SIZE:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        try:
            return cipher.decrypt_and_verify(ct, tag)
        except (ValueError, KeyError):
            return None

    # ------------------------------------------------------------------
    # Page table serialization
    # ------------------------------------------------------------------

    def _serialize_pt(self, name: str) -> bytes:
        entries_list = []
        for (d, k), entry in self._basis_entries[name].items():
            entries_list.append({
                "d": d, "k": k,
                "p": entry["pages"], "l": entry["total_len"],
            })
        pt = {"m": self.PT_MAGIC, "e": entries_list}
        return json.dumps(pt, separators=(',', ':')).encode('utf-8')

    def _deserialize_pt(self, data: bytes) -> dict:
        text = data.rstrip(b'\x00').decode('utf-8')
        pt = json.loads(text)
        if pt.get("m") != self.PT_MAGIC:
            raise ValueError("Bad magic")
        entries: dict[tuple[str, str], dict] = {}
        for e in pt["e"]:
            entries[(e["d"], e["k"])] = {
                "pages": e["p"], "total_len": e["l"],
            }
        return entries

    def _flush_pt(self, name: str) -> None:
        key = self._basis_keys[name]
        pt_idx = self._basis_pt_page[name]
        pt_bytes = self._serialize_pt(name)
        encrypted = self._encrypt(key, pt_bytes)
        self._write_page(pt_idx, encrypted)

    def _flush_image(self) -> None:
        with open(self.image_path, 'wb') as f:
            f.write(self._image)

    # ------------------------------------------------------------------
    # Used-page tracking
    # ------------------------------------------------------------------

    def _used_pages(self) -> set[int]:
        used: set[int] = set()
        for name in self._unlock_order:
            used.add(self._basis_pt_page[name])
            for entry in self._basis_entries[name].values():
                used.update(entry["pages"])
        return used

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def format(self, system_password: str) -> None:
        """Format disk: initialize pages, create .System basis."""
        self._image = bytearray(self.num_pages * self.page_size)
        self._basis_keys.clear()
        self._basis_pt_page.clear()
        self._basis_entries.clear()
        self._unlock_order.clear()
        self.create_basis(".System", system_password)
        self._flush_image()

    def create_basis(self, name: str, password: str) -> None:
        """Create and unlock a new basis."""
        if name in self._basis_keys:
            raise ValueError(f"Basis '{name}' already unlocked")
        key = self._derive_key(name, password)
        base_loc = self._derive_pt_location(key)
        used = self._used_pages()
        pt_idx = None
        for i in range(self.MAX_PROBE):
            candidate = (base_loc + i) % self.num_pages
            if candidate not in used:
                pt_idx = candidate
                break
        if pt_idx is None:
            raise RuntimeError("No free page-table slot")

        self._basis_keys[name] = key
        self._basis_pt_page[name] = pt_idx
        self._basis_entries[name] = {}
        self._unlock_order.append(name)
        self._flush_pt(name)
        self._flush_image()

    def unlock_basis(self, name: str, password: str) -> bool:
        """Unlock an existing basis by trial-decrypting its page table."""
        if name in self._basis_keys:
            return True
        key = self._derive_key(name, password)
        base_loc = self._derive_pt_location(key)
        for i in range(self.MAX_PROBE):
            candidate = (base_loc + i) % self.num_pages
            page_data = self._read_page(candidate)
            plaintext = self._decrypt(key, page_data)
            if plaintext is not None:
                try:
                    entries = self._deserialize_pt(plaintext)
                    self._basis_keys[name] = key
                    self._basis_pt_page[name] = candidate
                    self._basis_entries[name] = entries
                    self._unlock_order.append(name)
                    return True
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError,
                        KeyError):
                    continue
        return False

    def lock_basis(self, name: str) -> None:
        """Lock a basis: zeroize key in memory, leave ciphertext on disk."""
        if name not in self._basis_keys:
            return
        self._basis_keys[name] = b'\x00' * 32
        del self._basis_keys[name]
        del self._basis_pt_page[name]
        del self._basis_entries[name]
        self._unlock_order.remove(name)

    def is_basis_unlocked(self, name: str) -> bool:
        return name in self._basis_keys

    def get_unlocked_bases(self) -> list[str]:
        return list(self._unlock_order)

    def put(self, dictionary: str, key: str, value: bytes,
            basis: str = None) -> None:
        if basis is None:
            if not self._unlock_order:
                raise RuntimeError("No unlocked basis")
            basis = self._unlock_order[-1]
        if basis not in self._basis_keys:
            raise ValueError(f"Basis '{basis}' not unlocked")

        enc_key = self._basis_keys[basis]
        entries = self._basis_entries[basis]
        ekey = (dictionary, key)

        used = self._used_pages()

        num_needed = max(1, -(-len(value) // self.payload_size))

        # Free old pages when updating
        if ekey in entries:
            for p in entries[ekey]["pages"]:
                self._write_page(p, b'\x00' * self.page_size)
                used.discard(p)

        # Allocate fresh pages
        new_pages: list[int] = []
        for page_idx in range(self.num_pages):
            if page_idx not in used:
                new_pages.append(page_idx)
                used.add(page_idx)
                if len(new_pages) == num_needed:
                    break
        if len(new_pages) < num_needed:
            raise RuntimeError("Disk full")

        # Write encrypted data pages
        for i, p in enumerate(new_pages):
            start = i * self.payload_size
            end = min(start + self.payload_size, len(value))
            chunk = value[start:end] if start < len(value) else b""
            self._write_page(p, self._encrypt(enc_key, chunk))

        entries[ekey] = {"pages": new_pages, "total_len": len(value)}
        self._flush_pt(basis)
        self._flush_image()

    def get(self, dictionary: str, key: str,
            basis: str = None):
        if basis is not None:
            return self._get_from_basis(basis, dictionary, key)
        for name in self._unlock_order:
            val = self._get_from_basis(name, dictionary, key)
            if val is not None:
                return val
        return None

    def _get_from_basis(self, basis: str, dictionary: str, key: str):
        if basis not in self._basis_keys:
            return None
        entries = self._basis_entries[basis]
        ekey = (dictionary, key)
        if ekey not in entries:
            return None
        entry = entries[ekey]
        enc_key = self._basis_keys[basis]
        result = bytearray()
        for p in entry["pages"]:
            plaintext = self._decrypt(enc_key, self._read_page(p))
            if plaintext is None:
                return None
            result.extend(plaintext)
        return bytes(result[:entry["total_len"]])

    def delete(self, dictionary: str, key: str,
               basis: str = None) -> bool:
        if basis is None:
            target = None
            for name in reversed(self._unlock_order):
                if (dictionary, key) in self._basis_entries[name]:
                    target = name
                    break
            if target is None:
                return False
            basis = target

        if basis not in self._basis_keys:
            return False
        entries = self._basis_entries[basis]
        ekey = (dictionary, key)
        if ekey not in entries:
            return False

        for p in entries[ekey]["pages"]:
            self._write_page(p, b'\x00' * self.page_size)
        del entries[ekey]

        self._flush_pt(basis)
        self._flush_image()
        return True

    def list_keys(self, dictionary: str) -> list[str]:
        keys: set[str] = set()
        for name in self._unlock_order:
            for (d, k) in self._basis_entries[name]:
                if d == dictionary:
                    keys.add(k)
        return sorted(keys)

    def list_dictionaries(self) -> list[str]:
        dicts: set[str] = set()
        for name in self._unlock_order:
            for (d, _k) in self._basis_entries[name]:
                dicts.add(d)
        return sorted(dicts)

    def churn(self) -> None:
        """Re-encrypt used pages with fresh nonces."""
        page_owners: dict[int, tuple[str, str]] = {}
        for name in self._unlock_order:
            page_owners[self._basis_pt_page[name]] = (name, "pt")
            for entry in self._basis_entries[name].values():
                for p in entry["pages"]:
                    page_owners[p] = (name, "data")

        for page_idx in range(self.num_pages):
            if page_idx in page_owners:
                name, ptype = page_owners[page_idx]
                enc_key = self._basis_keys[name]
                if ptype == "pt":
                    self._flush_pt(name)
                else:
                    page_data = self._read_page(page_idx)
                    plaintext = self._decrypt(enc_key, page_data)
                    if plaintext is not None:
                        self._write_page(
                            page_idx, self._encrypt_raw(enc_key, plaintext)
                        )

        self._flush_image()

    def close(self) -> None:
        """Flush image and zeroize all key material."""
        if self._image is not None:
            self._flush_image()
        for name in list(self._basis_keys):
            self._basis_keys[name] = b'\x00' * 32
        self._basis_keys.clear()
        self._basis_pt_page.clear()
        self._basis_entries.clear()
        self._unlock_order.clear()
