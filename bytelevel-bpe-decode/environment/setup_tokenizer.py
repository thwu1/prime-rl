#!/usr/bin/env python3
"""Generate tokenizer.json, sequences.json, and expected_hashes.txt for the task."""
import hashlib
import json
import os


def bytes_to_unicode():
    """GPT-2 byte-to-unicode mapping.

    Printable bytes (33-126, 161-172, 174-255) map to their own codepoint.
    Non-printable bytes (0-32, 127-160, 173) map to U+0100 onward.
    """
    bs = (list(range(ord("!"), ord("~") + 1))
          + list(range(0xA1, 0xAC + 1))
          + list(range(0xAE, 0xFF + 1)))
    cs = list(bs)
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}


def byte_level_normalize(text, b2u):
    """ByteLevel normalization: each UTF-8 byte -> mapped Unicode char."""
    return "".join(b2u[b] for b in text.encode("utf-8"))


def main():
    os.makedirs("/app", exist_ok=True)
    b2u = bytes_to_unicode()

    # ── Base vocabulary: 256 single-byte tokens (ID == byte value) ──
    vocab = {}
    for byte_val in range(256):
        vocab[b2u[byte_val]] = byte_val

    # ── BPE merges ──
    space = b2u[32]          # Ġ (chr(288))
    merges_list = []

    def add_merge(a, b):
        merges_list.append(f"{a} {b}")
        return a + b

    gt       = add_merge(space, "t")            # Ġt
    _        = add_merge(space, "a")             # Ġa
    he       = add_merge("h", "e")               # he
    gth      = add_merge(gt, "h")                # Ġth
    gthe     = add_merge(gth, "e")               # Ġthe
    _        = add_merge("i", "n")               # in
    gw       = add_merge(space, "w")             # Ġw
    _or      = add_merge("o", "r")               # or
    gwor     = add_merge(gw, _or)                # Ġwor
    ld       = add_merge("l", "d")               # ld
    gworld   = add_merge(gwor, ld)               # Ġworld
    gi       = add_merge(space, "i")             # Ġi
    gis      = add_merge(gi, "s")                # Ġis
    hel      = add_merge(he, "l")                # hel
    hell     = add_merge(hel, "l")               # hell
    hello    = add_merge(hell, "o")              # hello
    gH       = add_merge(space, "H")             # ĠH
    gHe      = add_merge(gH, "e")                # ĠHe
    gHel     = add_merge(gHe, "l")               # ĠHel
    gHell    = add_merge(gHel, "l")              # ĠHell
    gHello   = add_merge(gHell, "o")             # ĠHello
    gm       = add_merge(space, "m")             # Ġm
    gme      = add_merge(gm, "e")                # Ġme
    ss       = add_merge("s", "s")               # ss
    ag       = add_merge("a", "g")               # ag
    age      = add_merge(ag, "e")                # age
    gmess    = add_merge(gme, ss)                # Ġmess
    gmessage = add_merge(gmess, age)             # Ġmessage

    # Assign merge-token IDs starting at 256
    merge_tokens = [
        gt, space + "a", he, gth, gthe,
        "in", gw, _or, gwor, ld, gworld,
        gi, gis, hel, hell, hello,
        gH, gHe, gHel, gHell, gHello,
        gm, gme, ss, ag, age, gmess, gmessage,
    ]
    for i, tok in enumerate(merge_tokens):
        vocab[tok] = 256 + i

    # ── Added tokens ──
    added_tokens = [
        {"id": 300, "content": "Začnimo",       "single_word": False,
         "lstrip": False, "rstrip": False, "normalized": True,  "special": False},
        {"id": 301, "content": "kuća",           "single_word": False,
         "lstrip": False, "rstrip": False, "normalized": True,  "special": False},
        {"id": 302, "content": "međa",           "single_word": False,
         "lstrip": False, "rstrip": False, "normalized": True,  "special": False},
        {"id": 303, "content": "München",        "single_word": False,
         "lstrip": False, "rstrip": False, "normalized": True,  "special": False},
        {"id": 304, "content": "<|endoftext|>",  "single_word": False,
         "lstrip": False, "rstrip": False, "normalized": False, "special": True},
        {"id": 305, "content": "Łódź",           "single_word": False,
         "lstrip": False, "rstrip": False, "normalized": True,  "special": False},
        {"id": 306, "content": "naïve",          "single_word": False,
         "lstrip": False, "rstrip": False, "normalized": True,  "special": False},
        {"id": 307, "content": "café",           "single_word": False,
         "lstrip": False, "rstrip": False, "normalized": False, "special": False},
    ]

    # ── Tokenizer config ──
    tokenizer_config = {
        "version": "1.0",
        "model": {
            "type": "BPE",
            "dropout": None,
            "unk_token": None,
            "continuing_subword_prefix": "",
            "end_of_word_suffix": "",
            "fuse_unk": False,
            "byte_fallback": False,
            "vocab": vocab,
            "merges": merges_list,
        },
        "normalizer": {"type": "ByteLevel"},
        "pre_tokenizer": {
            "type": "ByteLevel",
            "add_prefix_space": False,
            "trim_offsets": True,
            "use_regex": True,
        },
        "post_processor": None,
        "decoder": {
            "type": "ByteLevel",
            "add_prefix_space": True,
            "trim_offsets": True,
            "use_regex": True,
        },
        "added_tokens": added_tokens,
    }

    with open("/app/tokenizer.json", "w", encoding="utf-8") as f:
        json.dump(tokenizer_config, f, ensure_ascii=False, indent=2)

    # ── Encoded sequences ──
    sequences = {
        "sequences": [
            {"id": "seq_basic",
             "token_ids": [104, 101, 108, 108, 111]},
            {"id": "seq_bpe",
             "token_ids": [271, 266]},
            {"id": "seq_space_bpe",
             "token_ids": [260, 283]},
            {"id": "seq_added_czech",
             "token_ids": [300]},
            {"id": "seq_added_serbian",
             "token_ids": [301]},
            {"id": "seq_added_croatian",
             "token_ids": [302]},
            {"id": "seq_mixed",
             "token_ids": [271, 32, 300, 260, 283]},
            {"id": "seq_multi_added",
             "token_ids": [300, 32, 301, 32, 302]},
            {"id": "seq_newline",
             "token_ids": [271, 10, 119, 111, 114, 108, 100]},
            {"id": "seq_special",
             "token_ids": [271, 304, 266]},
            {"id": "seq_munchen",
             "token_ids": [303]},
            {"id": "seq_lodz",
             "token_ids": [305]},
            {"id": "seq_cross_utf8",
             "token_ids": [104, 195, 188, 116]},
            {"id": "seq_sentence",
             "token_ids": [271, 266, 268, 32, 300]},
            {"id": "seq_naive",
             "token_ids": [306]},
            {"id": "seq_european_cities",
             "token_ids": [305, 32, 303, 32, 300, 32, 301]},
            {"id": "seq_cafe",
             "token_ids": [307]},
            {"id": "seq_mixed_norm",
             "token_ids": [300, 32, 307]},
        ]
    }

    with open("/app/sequences.json", "w", encoding="utf-8") as f:
        json.dump(sequences, f, ensure_ascii=False, indent=2)

    # ── Expected outputs and SHA-256 hashes ──
    expected_outputs = {
        "seq_basic":            "hello",
        "seq_bpe":              "hello world",
        "seq_space_bpe":        " the message",
        "seq_added_czech":      "Začnimo",
        "seq_added_serbian":    "kuća",
        "seq_added_croatian":   "međa",
        "seq_mixed":            "hello Začnimo the message",
        "seq_multi_added":      "Začnimo kuća međa",
        "seq_newline":          "hello\nworld",
        "seq_special":          "hello world",
        "seq_munchen":          "München",
        "seq_lodz":             "Łódź",
        "seq_cross_utf8":       "hüt",
        "seq_sentence":         "hello world is Začnimo",
        "seq_naive":            "naïve",
        "seq_european_cities":  "Łódź München Začnimo kuća",
        "seq_cafe":             "café",
        "seq_mixed_norm":       "Začnimo café",
    }

    with open("/app/expected_hashes.txt", "w", encoding="utf-8") as f:
        for key, value in expected_outputs.items():
            h = hashlib.sha256(value.encode("utf-8")).hexdigest()
            f.write(f"{key}\t{h}\n")

    # ── Sanity checks ──
    u2b = {v: k for k, v in b2u.items()}
    for at in added_tokens:
        if at.get("normalized", False):
            norm = byte_level_normalize(at["content"], b2u)
            recovered = bytes(u2b[c] for c in norm).decode("utf-8")
            assert recovered == at["content"], (
                f"Round-trip failed for {at['content']!r}: "
                f"normalized={norm!r}, recovered={recovered!r}"
            )

    print("Setup complete: /app/tokenizer.json, /app/sequences.json, "
          "/app/expected_hashes.txt created.")


if __name__ == "__main__":
    main()
