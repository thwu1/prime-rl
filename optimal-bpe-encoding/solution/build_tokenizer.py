#!/usr/bin/env python3
"""
Build /app/tokenizer.py and /app/tokenizer.db:
  1. Parse the offset-based binary model format (model.bin)
  2. Implement standard greedy BPE encoding
  3. Implement optimal (minimum-token) encoding via DP
  4. Count distinct optimal tokenizations
  5. Export merge table and encoding comparisons to SQLite
"""

import textwrap, pathlib, json, sqlite3, importlib.util, sys

code = textwrap.dedent(r'''
import struct


class BPETokenizer:
    """BPE tokenizer with binary model loading, greedy and optimal encoding."""

    def __init__(self):
        self.merges = {}       # (int, int) -> int
        self.vocab = {}        # int -> bytes
        self._tok_bytes = {}   # bytes -> int  (reverse of vocab)
        self._max_tok_len = 1

    # ------------------------------------------------------------------
    # Model I/O — offset-based packed binary format
    # ------------------------------------------------------------------

    def load(self, model_path: str) -> None:
        with open(model_path, "rb") as fh:
            raw = fh.read()

        # Header: 4-byte magic, 1-byte version, 2-byte uint16 LE merge count,
        #         4-byte uint32 LE data offset
        magic = raw[:4]
        assert magic == b"BPE1", f"Bad magic: {magic!r}"
        version = struct.unpack("<B", raw[4:5])[0]
        assert version == 1, f"Unsupported version: {version}"
        num_merges = struct.unpack("<H", raw[5:7])[0]
        data_offset = struct.unpack("<I", raw[7:11])[0]

        # Merge pairs start at data_offset
        merges = {}
        offset = data_offset
        for i in range(num_merges):
            p0, p1 = struct.unpack("<HH", raw[offset:offset + 4])
            merges[(p0, p1)] = 256 + i
            offset += 4

        self.merges = merges
        self._build_vocab()

    def _build_vocab(self) -> None:
        vocab = {i: bytes([i]) for i in range(256)}
        for (p0, p1), idx in self.merges.items():
            vocab[idx] = vocab[p0] + vocab[p1]
        self.vocab = vocab
        self._tok_bytes = {bseq: tid for tid, bseq in vocab.items()}
        self._max_tok_len = max(len(s) for s in self._tok_bytes) if self._tok_bytes else 1

    # ------------------------------------------------------------------
    # Decode
    # ------------------------------------------------------------------

    def decode(self, ids: list) -> str:
        return b"".join(self.vocab[tid] for tid in ids).decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Greedy encode  (standard BPE)
    # ------------------------------------------------------------------

    def greedy_encode(self, text: str) -> list:
        ids = list(text.encode("utf-8"))
        while len(ids) >= 2:
            pairs = {}
            for i in range(len(ids) - 1):
                p = (ids[i], ids[i + 1])
                if p not in pairs:
                    pairs[p] = self.merges.get(p, float("inf"))
            best = min(pairs, key=pairs.get)
            if best not in self.merges:
                break
            new_id = self.merges[best]
            out = []
            i = 0
            while i < len(ids):
                if i < len(ids) - 1 and (ids[i], ids[i + 1]) == best:
                    out.append(new_id)
                    i += 2
                else:
                    out.append(ids[i])
                    i += 1
            ids = out
        return ids

    # ------------------------------------------------------------------
    # Optimal encode  (minimum-token-count via DP)
    # ------------------------------------------------------------------

    def optimal_encode(self, text: str) -> list:
        data = text.encode("utf-8")
        n = len(data)
        if n == 0:
            return []

        INF = float("inf")
        dp = [INF] * (n + 1)        # dp[i] = min tokens for data[:i]
        parent = [None] * (n + 1)    # (start, token_id)
        dp[0] = 0

        tb = self._tok_bytes
        mtl = self._max_tok_len

        for i in range(1, n + 1):
            for length in range(1, min(i, mtl) + 1):
                j = i - length
                seg = bytes(data[j:i])
                if seg in tb and dp[j] + 1 < dp[i]:
                    dp[i] = dp[j] + 1
                    parent[i] = (j, tb[seg])

        # back-track
        tokens = []
        pos = n
        while pos > 0:
            j, tid = parent[pos]
            tokens.append(tid)
            pos = j
        tokens.reverse()
        return tokens

    # ------------------------------------------------------------------
    # Compression gap
    # ------------------------------------------------------------------

    def compression_gap(self, text: str) -> int:
        return len(self.greedy_encode(text)) - len(self.optimal_encode(text))

    # ------------------------------------------------------------------
    # Count optimal tokenizations
    # ------------------------------------------------------------------

    def count_optimal_tokenizations(self, text: str) -> int:
        data = text.encode("utf-8")
        n = len(data)
        if n == 0:
            return 1

        INF = float("inf")
        dp_min = [INF] * (n + 1)
        dp_cnt = [0] * (n + 1)
        dp_min[0] = 0
        dp_cnt[0] = 1

        tb = self._tok_bytes
        mtl = self._max_tok_len

        for i in range(1, n + 1):
            for length in range(1, min(i, mtl) + 1):
                j = i - length
                seg = bytes(data[j:i])
                if seg in tb:
                    cost = dp_min[j] + 1
                    if cost < dp_min[i]:
                        dp_min[i] = cost
                        dp_cnt[i] = dp_cnt[j]
                    elif cost == dp_min[i]:
                        dp_cnt[i] += dp_cnt[j]

        return dp_cnt[n]
''').lstrip()

pathlib.Path("/app/tokenizer.py").write_text(code, encoding="utf-8")
print("Wrote /app/tokenizer.py")

# ----- Load and self-test -----
spec = importlib.util.spec_from_file_location("tokenizer", "/app/tokenizer.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

tok = mod.BPETokenizer()
tok.load("/app/model.bin")

# Verify trap strings
assert tok.compression_gap("pqrs") == 1, "pqrs gap"
assert tok.compression_gap("{|}") == 1, "{|} gap"
assert tok.compression_gap("JKLM") == 1, "JKLM gap"
assert tok.compression_gap("#$%&'") == 2, "#$%&' gap"
assert tok.compression_gap(":;<=>?@") == 3, ":;<=>?@ gap"
assert tok.compression_gap("in the JKLM") == 2, "in the JKLM gap"

# Verify counting
assert tok.count_optimal_tokenizations("the") == 2
assert tok.count_optimal_tokenizations("there") == 3
assert tok.count_optimal_tokenizations("therethe") == 6

# Verify roundtrips
for s in ["", "hello", "pqrs", ":;<=>?@", "in the JKLM"]:
    assert tok.decode(tok.optimal_encode(s)) == s, f"roundtrip {s!r}"

# Verify vocab attribute
assert isinstance(tok.vocab, dict)
assert tok.vocab[0] == b'\x00'
assert tok.vocab[97] == b'a'
assert len(tok.vocab) == 306

print("All self-tests passed.")

# ----- Create SQLite database -----
conn = sqlite3.connect("/app/tokenizer.db")
c = conn.cursor()

c.execute("""CREATE TABLE merges (
    rank INTEGER PRIMARY KEY,
    parent0 INTEGER NOT NULL,
    parent1 INTEGER NOT NULL,
    merged_id INTEGER NOT NULL,
    merged_bytes_hex TEXT NOT NULL
)""")

for (p0, p1), idx in tok.merges.items():
    rank = idx - 256
    hex_bytes = tok.vocab[idx].hex()
    c.execute("INSERT INTO merges VALUES (?, ?, ?, ?, ?)",
              (rank, p0, p1, idx, hex_bytes))

c.execute("""CREATE TABLE encodings (
    input_text TEXT PRIMARY KEY,
    greedy_ids TEXT NOT NULL,
    greedy_count INTEGER NOT NULL,
    optimal_ids TEXT NOT NULL,
    optimal_count INTEGER NOT NULL,
    gap INTEGER NOT NULL
)""")

with open("/app/test_vectors.json") as f:
    data = json.load(f)

for vec in data["vectors"]:
    if "reference_tokens" in vec and "min_tokens" in vec:
        text = vec["input"]
        g = tok.greedy_encode(text)
        o = tok.optimal_encode(text)
        c.execute("INSERT INTO encodings VALUES (?, ?, ?, ?, ?, ?)",
                  (text, json.dumps(g), len(g), json.dumps(o), len(o),
                   len(g) - len(o)))

conn.commit()
conn.close()
print("Wrote /app/tokenizer.db")
