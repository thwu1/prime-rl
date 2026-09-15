"""
BPE Tokenizer — reference implementation.

Loads minbpe v1 TEXT-format models only. The encode() method is intended
to produce optimal (minimum-token) encodings, but quality audits have
shown discrepancies on certain inputs. See test_vectors.json for details.
"""


class BPETokenizer:

    def __init__(self):
        self.merges = {}   # (int, int) -> int
        self.vocab = {}    # int -> bytes

    def load(self, model_path: str) -> None:
        """Load a minbpe v1 text-format model file.

        Format:
            Line 1: "minbpe v1"
            Line 2: regex pattern (may be empty)
            Line 3: number of special tokens
            Next N lines: special tokens
            Remaining lines: "parent0 parent1" merge pairs
        """
        merges = {}
        idx = 256
        with open(model_path, "r", encoding="utf-8") as fh:
            version = fh.readline().strip()
            assert version == "minbpe v1", f"Unknown format: {version}"
            _pattern = fh.readline().strip()
            num_special = int(fh.readline().strip())
            for _ in range(num_special):
                fh.readline()
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                p0, p1 = map(int, line.split())
                merges[(p0, p1)] = idx
                idx += 1
        self.merges = merges
        self._build_vocab()

    def _build_vocab(self) -> None:
        vocab = {i: bytes([i]) for i in range(256)}
        for (p0, p1), idx in self.merges.items():
            vocab[idx] = vocab[p0] + vocab[p1]
        self.vocab = vocab

    def decode(self, ids: list) -> str:
        return b"".join(self.vocab[tid] for tid in ids).decode(
            "utf-8", errors="replace"
        )

    def encode(self, text: str) -> list:
        """Encode text into the optimal (minimum) number of tokens.

        Applies merges in rank order to compress the byte sequence.
        """
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
