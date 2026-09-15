#!/usr/bin/env python3
"""ByteLevel BPE tokenizer decode pipeline — reference solution.

Implements the full GPT-2-style ByteLevel decode from first principles:
1. bytes_to_unicode(): the byte-to-char mapping where printable bytes keep
   their codepoint and non-printable bytes are offset to U+0100+.
2. ByteLevel normalization for added tokens (normalized=true): each UTF-8
   byte of the token content is mapped through bytes_to_unicode to produce
   the form that the ByteLevel decoder can invert.
3. Direct passthrough for non-normalized added tokens: their content is
   output as-is without ByteLevel decode.
4. ByteLevel decode: each character in the token string is mapped back to
   its byte via the inverse mapping, then the concatenated bytes are
   interpreted as UTF-8.
"""

import json


def bytes_to_unicode():
    """GPT-2 byte-to-unicode mapping.

    Printable bytes (33-126, 161-172, 174-255) map to chr(byte_value).
    The remaining 68 non-printable bytes (0-32, 127-160, 173) map to
    chr(256), chr(257), ..., chr(323) in iteration order.
    """
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(0xA1, 0xAC + 1))
        + list(range(0xAE, 0xFF + 1))
    )
    cs = list(bs)
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}


def byte_level_normalize(text, b2u):
    """Apply ByteLevel normalization: each UTF-8 byte -> mapped char."""
    return "".join(b2u[b] for b in text.encode("utf-8"))


def main():
    # Load configuration
    with open("/app/tokenizer.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    with open("/app/sequences.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    # Build byte <-> char mappings
    b2u = bytes_to_unicode()
    u2b = {v: k for k, v in b2u.items()}

    # Invert model vocab: ID -> token string
    vocab = config["model"]["vocab"]
    id_to_token = {v: k for k, v in vocab.items()}

    # Index added tokens
    added_tokens_by_id = {}
    special_token_ids = set()
    non_normalized_ids = set()
    for at in config.get("added_tokens", []):
        added_tokens_by_id[at["id"]] = at
        if at.get("special", False):
            special_token_ids.add(at["id"])
        if not at.get("normalized", True):
            non_normalized_ids.add(at["id"])

    # Pre-compute ByteLevel-normalized forms for normalized added tokens
    normalizer_type = (config.get("normalizer") or {}).get("type")
    normalized_forms = {}
    if normalizer_type == "ByteLevel":
        for at in config.get("added_tokens", []):
            if at.get("normalized", False) and not at.get("special", False):
                normalized_forms[at["id"]] = byte_level_normalize(
                    at["content"], b2u
                )

    # Decode each sequence (skip_special_tokens=True)
    results = {}
    for seq in data["sequences"]:
        seq_id = seq["id"]
        token_ids = seq["token_ids"]

        output_parts = []
        byte_buffer = []

        def flush_bytes():
            if byte_buffer:
                output_parts.append(
                    bytes(byte_buffer).decode("utf-8", errors="replace")
                )
                byte_buffer.clear()

        def add_to_byte_buffer(token_str):
            for c in token_str:
                b = u2b.get(c)
                if b is not None:
                    byte_buffer.append(b)
                else:
                    byte_buffer.extend(c.encode("utf-8"))

        for tid in token_ids:
            # Skip special tokens
            if tid in special_token_ids:
                continue

            if tid in added_tokens_by_id:
                at = added_tokens_by_id[tid]
                if tid in non_normalized_ids:
                    # Non-normalized added token: flush and output directly
                    flush_bytes()
                    output_parts.append(at["content"])
                else:
                    # Normalized added token: use normalized form
                    ts = normalized_forms.get(tid, at["content"])
                    add_to_byte_buffer(ts)
            elif tid in id_to_token:
                # Regular vocab token
                add_to_byte_buffer(id_to_token[tid])

        # Flush remaining bytes
        flush_bytes()
        results[seq_id] = "".join(output_parts)

    # Write output
    with open("/app/decoded_output.json", "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
