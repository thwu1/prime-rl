#!/usr/bin/env python3
"""
Plausibly Deniable Database (PDDB) — Extended with FastSpace cache
and portable encrypted export with CLI-verifiable HMAC integrity.
"""

import os
import json
import hmac
import hashlib
import base64

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes


class PDDB:
    NONCE_SIZE = 12
    TAG_SIZE = 16
    MAX_PROBE = 32
    PT_MAGIC = "PDDB_PT"
    FS_MAGIC = "PDDB_FS"

    def __init__(self, image_path: str, num_pages: int = 256,
                 page_size: int = 4096, fastspace_limit: int = 16):
        self.image_path = image_path
        self.num_pages = num_pages
        self.page_size = page_size
        self.payload_size = page_size - self.NONCE_SIZE - self.TAG_SIZE
        self.fastspace_limit = fastspace_limit

        self._basis_keys: dict[str, bytes] = {}
        self._basis_pt_page: dict[str, int] = {}
        self._basis_entries: dict[str, dict] = {}
        self._unlock_order: list[str] = []

        # FastSpace cache state
        self._fastspace_cache: list[int] = []
        self._fastspace_page: int | None = None

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
        prk = hmac.new(
            name.encode('utf-8'), password.encode('utf-8'), hashlib.sha256
        ).digest()
        okm = hmac.new(prk, b"pddb-basis-key\x01", hashlib.sha256).digest()
        return okm

    def _derive_pt_location(self, key: bytes) -> int:
        h = hmac.new(key, b"pddb-pt-location", hashlib.sha256).digest()
        return int.from_bytes(h[:4], 'big') % self.num_pages

    def _derive_fs_location(self, key: bytes) -> int:
        """Derive FastSpace page location from system key."""
        h = hmac.new(key, b"pddb-fs-location", hashlib.sha256).digest()
        return int.from_bytes(h[:4], 'big') % self.num_pages

    def _encrypt(self, key: bytes, plaintext: bytes) -> bytes:
        if len(plaintext) > self.payload_size:
            raise ValueError("Plaintext exceeds page payload capacity")
        padded = plaintext + b'\x00' * (self.payload_size - len(plaintext))
        nonce = get_random_bytes(self.NONCE_SIZE)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ct, tag = cipher.encrypt_and_digest(padded)
        return nonce + ct + tag

    def _encrypt_raw(self, key: bytes, padded_plaintext: bytes) -> bytes:
        assert len(padded_plaintext) == self.payload_size
        nonce = get_random_bytes(self.NONCE_SIZE)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ct, tag = cipher.encrypt_and_digest(padded_plaintext)
        return nonce + ct + tag

    def _decrypt(self, key: bytes, page_data: bytes):
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
    # Page table serialization (extended with FastSpace page reference)
    # ------------------------------------------------------------------

    def _serialize_pt(self, name: str) -> bytes:
        entries_list = []
        for (d, k), entry in self._basis_entries[name].items():
            entries_list.append({
                "d": d, "k": k,
                "p": entry["pages"], "l": entry["total_len"],
            })
        pt: dict = {"m": self.PT_MAGIC, "e": entries_list}
        if name == ".System" and self._fastspace_page is not None:
            pt["fp"] = self._fastspace_page
        return json.dumps(pt, separators=(',', ':')).encode('utf-8')

    def _deserialize_pt(self, data: bytes) -> tuple[dict, int | None]:
        text = data.rstrip(b'\x00').decode('utf-8')
        pt = json.loads(text)
        if pt.get("m") != self.PT_MAGIC:
            raise ValueError("Bad magic")
        entries: dict[tuple[str, str], dict] = {}
        for e in pt["e"]:
            entries[(e["d"], e["k"])] = {
                "pages": e["p"], "total_len": e["l"],
            }
        return entries, pt.get("fp")

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
    # FastSpace cache persistence
    # ------------------------------------------------------------------

    def _serialize_fs(self) -> bytes:
        fs = {"m": self.FS_MAGIC, "c": self._fastspace_cache}
        return json.dumps(fs, separators=(',', ':')).encode('utf-8')

    def _deserialize_fs(self, data: bytes) -> list[int]:
        text = data.rstrip(b'\x00').decode('utf-8')
        fs = json.loads(text)
        if fs.get("m") != self.FS_MAGIC:
            raise ValueError("Bad FS magic")
        return fs["c"]

    def _flush_fs(self) -> None:
        if self._fastspace_page is None or ".System" not in self._basis_keys:
            return
        key = self._basis_keys[".System"]
        fs_bytes = self._serialize_fs()
        encrypted = self._encrypt(key, fs_bytes)
        self._write_page(self._fastspace_page, encrypted)

    def _load_fs(self) -> None:
        if self._fastspace_page is None or ".System" not in self._basis_keys:
            return
        key = self._basis_keys[".System"]
        page_data = self._read_page(self._fastspace_page)
        plaintext = self._decrypt(key, page_data)
        if plaintext is not None:
            try:
                self._fastspace_cache = self._deserialize_fs(plaintext)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, KeyError):
                self._fastspace_cache = []

    def _init_fastspace_page(self) -> None:
        """Allocate a page for the FastSpace cache."""
        if ".System" not in self._basis_keys:
            return
        sys_key = self._basis_keys[".System"]
        base_loc = self._derive_fs_location(sys_key)
        used = self._used_pages()
        for i in range(self.MAX_PROBE):
            candidate = (base_loc + i) % self.num_pages
            if candidate not in used:
                self._fastspace_page = candidate
                return
        raise RuntimeError("No free page for FastSpace cache")

    # ------------------------------------------------------------------
    # Used-page tracking
    # ------------------------------------------------------------------

    def _used_pages(self) -> set[int]:
        used: set[int] = set()
        for name in self._unlock_order:
            used.add(self._basis_pt_page[name])
            for entry in self._basis_entries[name].values():
                used.update(entry["pages"])
        if self._fastspace_page is not None:
            used.add(self._fastspace_page)
        return used

    # ------------------------------------------------------------------
    # FastSpace public API
    # ------------------------------------------------------------------

    def get_fastspace_count(self) -> int:
        return len(self._fastspace_cache)

    def refresh_fastspace(self) -> None:
        used = self._used_pages()
        cache: list[int] = []
        for i in range(self.num_pages):
            if i not in used and len(cache) < self.fastspace_limit:
                cache.append(i)
        self._fastspace_cache = cache
        self._flush_fs()
        self._flush_image()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def format(self, system_password: str) -> None:
        self._image = bytearray(get_random_bytes(self.num_pages * self.page_size))
        self._basis_keys.clear()
        self._basis_pt_page.clear()
        self._basis_entries.clear()
        self._unlock_order.clear()
        self._fastspace_cache = []
        self._fastspace_page = None

        self.create_basis(".System", system_password)
        self._init_fastspace_page()
        self._flush_pt(".System")  # re-flush PT to include FS page reference
        self.refresh_fastspace()
        self._flush_image()

    def create_basis(self, name: str, password: str) -> None:
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

        # Remove PT page from cache if present
        if pt_idx in self._fastspace_cache:
            self._fastspace_cache.remove(pt_idx)

        self._flush_pt(name)
        self._flush_fs()
        self._flush_image()

    def unlock_basis(self, name: str, password: str) -> bool:
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
                    entries, fs_page = self._deserialize_pt(plaintext)
                    self._basis_keys[name] = key
                    self._basis_pt_page[name] = candidate
                    self._basis_entries[name] = entries
                    self._unlock_order.append(name)

                    # Load FastSpace cache when unlocking .System
                    if name == ".System" and fs_page is not None:
                        self._fastspace_page = fs_page
                        self._load_fs()

                    return True
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError,
                        KeyError):
                    continue
        return False

    def lock_basis(self, name: str) -> None:
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
                self._write_page(p, get_random_bytes(self.page_size))
                used.discard(p)
                if len(self._fastspace_cache) < self.fastspace_limit:
                    self._fastspace_cache.append(p)

        # Allocate: draw from FastSpace cache first
        new_pages: list[int] = []
        cache_snapshot = list(self._fastspace_cache)
        for p in cache_snapshot:
            if p not in used:
                new_pages.append(p)
                used.add(p)
                self._fastspace_cache.remove(p)
                if len(new_pages) == num_needed:
                    break

        # Fall back to full disk scan if cache insufficient
        if len(new_pages) < num_needed:
            for page_idx in range(self.num_pages):
                if page_idx not in used:
                    new_pages.append(page_idx)
                    used.add(page_idx)
                    if len(new_pages) == num_needed:
                        break

        if len(new_pages) < num_needed:
            raise RuntimeError("Disk full")

        for i, p in enumerate(new_pages):
            start = i * self.payload_size
            end = min(start + self.payload_size, len(value))
            chunk = value[start:end] if start < len(value) else b""
            self._write_page(p, self._encrypt(enc_key, chunk))

        entries[ekey] = {"pages": new_pages, "total_len": len(value)}
        self._flush_pt(basis)
        self._flush_fs()
        self._flush_image()

    def get(self, dictionary: str, key: str, basis: str = None):
        if basis is not None:
            return self._get_from_basis(basis, dictionary, key)
        for name in reversed(self._unlock_order):
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
            self._write_page(p, get_random_bytes(self.page_size))
            if len(self._fastspace_cache) < self.fastspace_limit:
                self._fastspace_cache.append(p)
        del entries[ekey]

        self._flush_pt(basis)
        self._flush_fs()
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
        page_owners: dict[int, tuple[str, str]] = {}
        for name in self._unlock_order:
            page_owners[self._basis_pt_page[name]] = (name, "pt")
            for entry in self._basis_entries[name].values():
                for p in entry["pages"]:
                    page_owners[p] = (name, "data")
        if self._fastspace_page is not None:
            page_owners[self._fastspace_page] = (".System", "fs")

        for page_idx in range(self.num_pages):
            if page_idx in page_owners:
                name, ptype = page_owners[page_idx]
                if ptype == "pt":
                    self._flush_pt(name)
                elif ptype == "fs":
                    self._flush_fs()
                else:
                    enc_key = self._basis_keys[name]
                    page_data = self._read_page(page_idx)
                    plaintext = self._decrypt(enc_key, page_data)
                    if plaintext is not None:
                        self._write_page(
                            page_idx, self._encrypt_raw(enc_key, plaintext)
                        )
            else:
                self._write_page(page_idx, get_random_bytes(self.page_size))

        self._flush_image()

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def export_basis(self, basis_name: str, password: str,
                     output_path: str) -> None:
        if basis_name not in self._basis_keys:
            raise ValueError(f"Basis '{basis_name}' not unlocked")

        salt = get_random_bytes(16).hex()

        # Derive HMAC key from password and salt
        hmac_key_hex = hmac.new(
            password.encode('utf-8'),
            (salt + ":export-hmac-key").encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        entries = []
        for (d, k) in sorted(self._basis_entries[basis_name].keys()):
            value = self._get_from_basis(basis_name, d, k)
            if value is None:
                continue
            data_b64 = base64.b64encode(value).decode('ascii')

            msg = f"{d}:{k}:{data_b64}"
            tag = hmac.new(
                hmac_key_hex.encode('utf-8'),
                msg.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            entries.append({
                "dictionary": d,
                "key": k,
                "data_b64": data_b64,
                "hmac": tag,
            })

        export_data = {
            "version": 1,
            "salt": salt,
            "entries": entries,
        }

        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)

    def import_basis(self, input_path: str, target_basis: str,
                     password: str) -> None:
        if target_basis not in self._basis_keys:
            raise ValueError(f"Basis '{target_basis}' not unlocked")

        with open(input_path, 'r') as f:
            export_data = json.load(f)

        salt = export_data["salt"]
        hmac_key_hex = hmac.new(
            password.encode('utf-8'),
            (salt + ":export-hmac-key").encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Verify ALL entries before writing any data
        for entry in export_data["entries"]:
            msg = f"{entry['dictionary']}:{entry['key']}:{entry['data_b64']}"
            expected = hmac.new(
                hmac_key_hex.encode('utf-8'),
                msg.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, entry["hmac"]):
                raise ValueError(
                    f"HMAC verification failed for "
                    f"{entry['dictionary']}/{entry['key']}"
                )

        # All verified — import entries
        for entry in export_data["entries"]:
            data = base64.b64decode(entry["data_b64"])
            self.put(entry["dictionary"], entry["key"], data,
                     basis=target_basis)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self._image is not None:
            self._flush_fs()
            self._flush_image()
        for name in list(self._basis_keys):
            self._basis_keys[name] = b'\x00' * 32
        self._basis_keys.clear()
        self._basis_pt_page.clear()
        self._basis_entries.clear()
        self._unlock_order.clear()
        self._fastspace_cache = []
        self._fastspace_page = None
