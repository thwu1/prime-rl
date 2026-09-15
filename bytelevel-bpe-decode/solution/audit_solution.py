#!/usr/bin/env python3
"""ByteLevel BPE tokenizer vulnerability auditor — reference solution.

Identifies added tokens containing normalization-hazardous Unicode characters:
characters whose codepoints fall within the bytes_to_unicode mapping domain
but whose UTF-8 byte encoding differs from the single byte that mapping
would produce. Such characters will corrupt to control characters or invalid
bytes if ByteLevel normalization is not correctly applied during decoding.
"""

import json


def bytes_to_unicode():
    """GPT-2 byte-to-unicode mapping."""
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


def main():
    with open("/app/tokenizer.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    b2u = bytes_to_unicode()
    u2b = {v: k for k, v in b2u.items()}

    hazardous_tokens = []
    safe_token_ids = []

    for at in config.get("added_tokens", []):
        content = at["content"]
        hazardous_chars = []

        for ch in content:
            if ch in u2b:
                mapped_byte = u2b[ch]
                utf8_bytes = ch.encode("utf-8")
                # Hazardous if the u2b single-byte result differs from
                # the character's actual UTF-8 encoding
                if utf8_bytes != bytes([mapped_byte]):
                    hazardous_chars.append(ch)

        if hazardous_chars:
            # high risk: normalized=false means decoder can't fix via normalization
            # low risk: normalized=true means a correct decoder handles it
            is_normalized = at.get("normalized", False)
            risk = "low" if is_normalized else "high"
            hazardous_tokens.append({
                "id": at["id"],
                "content": content,
                "hazardous_chars": hazardous_chars,
                "normalized": is_normalized,
                "risk": risk,
            })
        else:
            safe_token_ids.append(at["id"])

    n_high = sum(1 for t in hazardous_tokens if t["risk"] == "high")
    n_low = sum(1 for t in hazardous_tokens if t["risk"] == "low")

    summary = (
        f"Found {len(hazardous_tokens)} hazardous added tokens "
        f"({n_high} high-risk, {n_low} low-risk) and "
        f"{len(safe_token_ids)} safe tokens. "
        f"High-risk tokens have normalized=false, meaning ByteLevel "
        f"normalization cannot recover correct decode output for their "
        f"hazardous characters."
    )

    report = {
        "hazardous_tokens": hazardous_tokens,
        "safe_token_ids": safe_token_ids,
        "summary": summary,
    }

    with open("/app/audit_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
