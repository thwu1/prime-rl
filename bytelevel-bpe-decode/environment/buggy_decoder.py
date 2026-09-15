#!/usr/bin/env python3
"""Decode token ID sequences using a tokenizer configuration."""
import json


def build_byte_unicode_map():
    """Construct the byte-to-unicode character mapping used by ByteLevel tokenizers."""
    printable = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(0xA1, 0xAC + 1))
        + list(range(0xAE, 0xFF + 1))
    )
    byte_vals = list(printable)
    char_vals = list(printable)
    offset = 0
    for b in range(256):
        if b not in printable:
            byte_vals.append(b)
            char_vals.append(256 + offset)
            offset += 1
    return {b: chr(c) for b, c in zip(byte_vals, char_vals)}


def main():
    with open("/app/tokenizer.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    with open("/app/sequences.json", "r", encoding="utf-8") as f:
        sequences = json.load(f)

    b2u = build_byte_unicode_map()
    u2b = {v: k for k, v in b2u.items()}

    # Build token ID -> string mapping from model vocab
    vocab = config["model"]["vocab"]
    id_to_str = {token_id: token_str for token_str, token_id in vocab.items()}

    # Index added tokens by ID
    added_tokens = {}
    for entry in config.get("added_tokens", []):
        added_tokens[entry["id"]] = entry

    results = {}
    for seq in sequences["sequences"]:
        sid = seq["id"]
        token_ids = seq["token_ids"]

        # Collect token strings for each ID
        parts = []
        for tid in token_ids:
            if tid in added_tokens:
                parts.append(added_tokens[tid]["content"])
            elif tid in id_to_str:
                parts.append(id_to_str[tid])

        # ByteLevel decode: map each character back to its byte value
        raw_bytes = []
        for part in parts:
            for ch in part:
                if ch in u2b:
                    raw_bytes.append(u2b[ch])
                else:
                    raw_bytes.extend(ch.encode("utf-8"))

        results[sid] = bytes(raw_bytes).decode("utf-8", errors="replace")

    with open("/app/decoded_output.json", "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, ensure_ascii=False, indent=2)

    print(f"Decoded {len(results)} sequences to /app/decoded_output.json")


if __name__ == "__main__":
    main()
