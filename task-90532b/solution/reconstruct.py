#!/usr/bin/env python3
"""
Reconstruct and verify a content-addressable KVS Merkle tree.
Reads /app/content.sqlite and /app/roots.json.
Writes /app/output/manifest.json.
"""

import base64
import hashlib
import json
import os
import sqlite3


def sha1_blobref(data):
    return "sha1-" + hashlib.sha1(data).hexdigest()


def decode_val(treeobj):
    """Decode a val treeobj: base64 -> strip NUL -> JSON parse."""
    raw = base64.b64decode(treeobj["data"])
    if raw.endswith(b'\x00'):
        raw = raw[:-1]
    return json.loads(raw)


class Reconstructor:
    def __init__(self):
        self.conn = sqlite3.connect("/app/content.sqlite")
        with open("/app/roots.json") as f:
            self.roots = json.load(f)

        # All hashes present in the store
        self.all_hashes = set()
        for row in self.conn.execute("SELECT hash FROM objects"):
            self.all_hashes.add(row[0])

        # Tracking sets
        self.referenced = set()
        self.corrupted = []
        self.corrupted_set = set()
        self.dangling = []
        self.dangling_set = set()
        self.unreachable = []

        # Valid paths per namespace (for symlink resolution)
        self.valid_paths = {}

    def _ensure_ns(self, ns):
        if ns not in self.valid_paths:
            self.valid_paths[ns] = set()

    def load_and_verify(self, h):
        """Load blob by hash, verify SHA-1 integrity.
        Returns (data_bytes, is_valid).
        Tracks referenced hashes, corrupted blobs, and dangling refs.
        """
        self.referenced.add(h)

        if h not in self.all_hashes:
            if h not in self.dangling_set:
                self.dangling_set.add(h)
                self.dangling.append(h)
            return None, False

        row = self.conn.execute(
            "SELECT object_data FROM objects WHERE hash = ?", (h,)
        ).fetchone()
        data = row[0]
        actual = sha1_blobref(data)

        if actual != h:
            if h not in self.corrupted_set:
                self.corrupted_set.add(h)
                self.corrupted.append({
                    "stored_hash": h,
                    "computed_hash": actual,
                })
            return None, False

        return data, True

    def traverse(self, treeobj, ns, path=""):
        """Recursively traverse a treeobj, collecting resolved values and symlinks."""
        self._ensure_ns(ns)
        rv = {}
        sym = {}
        t = treeobj["type"]

        if t == "val":
            value = decode_val(treeobj)
            rv[path] = value
            self.valid_paths[ns].add(path)

        elif t == "valref":
            h = treeobj["data"][0]
            data, ok = self.load_and_verify(h)
            if not ok:
                self.unreachable.append(f"{ns}::{path}")
            else:
                try:
                    value = json.loads(data)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    value = data.decode("utf-8", errors="replace")
                rv[path] = value
                self.valid_paths[ns].add(path)

        elif t == "dirref":
            h = treeobj["data"][0]
            data, ok = self.load_and_verify(h)
            if not ok:
                key = f"{ns}::{path}" if path else f"{ns}::<root>"
                self.unreachable.append(key)
            else:
                if path:
                    self.valid_paths[ns].add(path)
                children = json.loads(data)
                for name in sorted(children.keys()):
                    child_treeobj = children[name]
                    child_path = f"{path}.{name}" if path else name
                    child_rv, child_sym = self.traverse(child_treeobj, ns, child_path)
                    rv.update(child_rv)
                    sym.update(child_sym)

        elif t == "symlink":
            d = treeobj["data"]
            if isinstance(d, str):
                sym[path] = {
                    "target": d,
                    "target_namespace": None,
                    "resolves": None,
                }
            else:
                sym[path] = {
                    "target": d["target"],
                    "target_namespace": d.get("namespace"),
                    "resolves": None,
                }

        return rv, sym

    def resolve_symlinks(self, ns_results):
        """After all namespaces are traversed, resolve symlink targets."""
        for ns_name, ns_data in ns_results.items():
            for path, info in ns_data["symlinks"].items():
                target = info["target"]
                target_ns = info["target_namespace"] or ns_name
                if target_ns in self.valid_paths and target in self.valid_paths[target_ns]:
                    info["resolves"] = True
                else:
                    info["resolves"] = False

    def run(self):
        ns_results = {}

        for ns_name in sorted(self.roots["namespaces"].keys()):
            ns_info = self.roots["namespaces"][ns_name]
            root_treeobj = ns_info["root"]
            root_hash = root_treeobj["data"][0]
            rv, sym = self.traverse(root_treeobj, ns_name)
            ns_results[ns_name] = {
                "root_hash": root_hash,
                "resolved_values": rv,
                "symlinks": sym,
            }

        self.resolve_symlinks(ns_results)

        total_blobs = len(self.all_hashes)
        orphaned = len(self.all_hashes - self.referenced)

        manifest = {
            "namespaces": ns_results,
            "integrity": {
                "total_blobs": total_blobs,
                "corrupted_blobs": self.corrupted,
                "dangling_refs": self.dangling,
                "unreachable_keys": self.unreachable,
            },
            "orphaned_blob_count": orphaned,
        }

        os.makedirs("/app/output", exist_ok=True)
        with open("/app/output/manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

        print(f"Manifest written to /app/output/manifest.json")
        print(f"  Namespaces: {sorted(ns_results.keys())}")
        print(f"  Total blobs: {total_blobs}")
        print(f"  Corrupted: {len(self.corrupted)}")
        print(f"  Dangling: {len(self.dangling)}")
        print(f"  Unreachable: {len(self.unreachable)}")
        print(f"  Orphaned: {orphaned}")

        self.conn.close()


if __name__ == "__main__":
    Reconstructor().run()
