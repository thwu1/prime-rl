#!/usr/bin/env python3
"""

Solution: Reads the fieldwork SQLite database, extracts numeral morphemes
from the JSON-encoded lexicon table, reads field observations for context,
reverse-engineers three numeral systems from training data patterns,
detects corrupted training entries, generates corrections, and processes
all test cases.
"""
import sqlite3
import json
import os


# ═══════════════════════════════════════════════════════════════════════════════
#  Database access — extract numeral morphemes from lexicon JSON blobs
# ═══════════════════════════════════════════════════════════════════════════════

def load_numeral_morphemes(conn):
    """Extract numeral morphemes from the lexicon table using json_extract."""
    morphemes = {}
    for row in conn.execute(
        "SELECT language, surface_form, "
        "CAST(json_extract(entry_data, '$.value') AS INTEGER) as value "
        "FROM lexicon "
        "WHERE json_extract(entry_data, '$.domain') = 'numeral' "
        "ORDER BY language, value"
    ):
        lang, form, value = row
        if lang not in morphemes:
            morphemes[lang] = {}
        morphemes[lang][form] = value
    return morphemes


def load_observations(conn):
    """Read field observations for contextual clues."""
    obs = []
    for row in conn.execute(
        "SELECT collector, language, date, obs_type, content "
        "FROM observations ORDER BY date, id"
    ):
        obs.append({
            "collector": row[0], "language": row[1], "date": row[2],
            "type": row[3], "content": row[4]
        })
    return obs


# ═══════════════════════════════════════════════════════════════════════════════
#  TURAHI  (base 8, multiplicative-additive)
#  Discovered from training data patterns:
#  - Values 1-7 are basic digits
#  - 8, 64, 512 are powers of 8 (grouping markers)
#  - Smaller before larger = multiply; larger before smaller = add
# ═══════════════════════════════════════════════════════════════════════════════

_T_DIGITS = {"na": 1, "fi": 2, "so": 3, "ke": 4, "mu": 5, "la": 6, "po": 7}
_T_DIGITS_R = {v: k for k, v in _T_DIGITS.items()}
_T_POWERS = {"dun": 8, "ram": 64, "vol": 512}
_T_POWERS_R = {8: "dun", 64: "ram", 512: "vol"}
_T_ALL = {**_T_DIGITS, **_T_POWERS}


def turahi_decode(word: str) -> int:
    tokens = word.split()
    value, cur = 0, 0
    for tok in tokens:
        tv = _T_ALL[tok]
        if cur == 0:
            cur = tv
        elif cur < tv:
            cur *= tv
        else:
            value += cur
            cur = tv
    return value + cur


def turahi_encode(n: int) -> str:
    parts = []
    for pv in (512, 64, 8):
        if n >= pv:
            d = n // pv
            n %= pv
            if d > 1:
                parts.append(_T_DIGITS_R[d])
            parts.append(_T_POWERS_R[pv])
    if n > 0:
        parts.append(_T_DIGITS_R[n])
    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
#  BELAGO  (base 20, sub-base 5, pivot-delimited)
#  Discovered from training data patterns:
#  - Values 1-4 are unit digits
#  - 5 and 10 are sub-base additive components
#  - 20 and 400 (=20^2) are pivot markers
#  - Tokens before a pivot multiply it; tokens after add
# ═══════════════════════════════════════════════════════════════════════════════

_B_UNIT = {"cha": 1, "doi": 2, "tin": 3, "pak": 4, "nen": 5, "tum": 10}
_B_UNIT_DIG = {1: "cha", 2: "doi", 3: "tin", 4: "pak"}


def _b_unit_dec(tokens):
    return sum(_B_UNIT[t] for t in tokens)


def _b_unit_enc(n):
    parts = []
    if n >= 10:
        parts.append("tum"); n -= 10
    if n >= 5:
        parts.append("nen"); n -= 5
    if n >= 1:
        parts.append(_B_UNIT_DIG[n])
    return parts


def belago_decode(word: str) -> int:
    tokens = word.split()
    total = 0

    if "bor" in tokens:
        bi = tokens.index("bor")
        mult = _b_unit_dec(tokens[:bi]) if bi > 0 else 1
        total += mult * 400
        tokens = tokens[bi + 1:]

    if "kal" in tokens:
        ki = tokens.index("kal")
        mult = _b_unit_dec(tokens[:ki]) if ki > 0 else 1
        total += mult * 20
        tokens = tokens[ki + 1:]

    if tokens:
        total += _b_unit_dec(tokens)
    return total


def belago_encode(n: int) -> str:
    parts = []
    if n >= 400:
        bc = n // 400; n %= 400
        if bc > 1:
            parts.extend(_b_unit_enc(bc))
        parts.append("bor")
    if n >= 20:
        kc = n // 20; n %= 20
        if kc > 1:
            parts.extend(_b_unit_enc(kc))
        parts.append("kal")
    if n > 0:
        parts.extend(_b_unit_enc(n))
    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
#  RENSHI  (base 12, subtractive fe-prefix for 8-11)
#  Discovered from training data patterns:
#  - Values 1-7 are basic digits
#  - 8-11 are derived via fe- prefix (complement: 12-digit_value)
#  - 12 and 144 (=12^2) are power markers
#  - Same multiplicative-additive rule as Turahi
# ═══════════════════════════════════════════════════════════════════════════════

_R_DIGITS = {"ek": 1, "dwa": 2, "tri": 3, "kat": 4,
             "pen": 5, "hes": 6, "sep": 7}
_R_SUB = {"fekat": 8, "fetri": 9, "fedwa": 10, "feek": 11}
_R_ALL_D = {**_R_DIGITS, **_R_SUB}
_R_ALL_D_R = {v: k for k, v in _R_ALL_D.items()}
_R_POWERS = {"zan": 12, "gros": 144}
_R_ALL = {**_R_ALL_D, **_R_POWERS}


def renshi_decode(word: str) -> int:
    tokens = word.split()
    value, cur = 0, 0
    for tok in tokens:
        tv = _R_ALL[tok]
        if cur == 0:
            cur = tv
        elif cur < tv:
            cur *= tv
        else:
            value += cur
            cur = tv
    return value + cur


def renshi_encode(n: int) -> str:
    parts = []
    if n >= 144:
        gc = n // 144; n %= 144
        if gc > 1:
            parts.append(_R_ALL_D_R[gc])
        parts.append("gros")
    if n >= 12:
        zc = n // 12; n %= 12
        if zc > 1:
            parts.append(_R_ALL_D_R[zc])
        parts.append("zan")
    if n > 0:
        parts.append(_R_ALL_D_R[n])
    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
#  Dispatch
# ═══════════════════════════════════════════════════════════════════════════════

DECODERS = {"turahi": turahi_decode, "belago": belago_decode, "renshi": renshi_decode}
ENCODERS = {"turahi": turahi_encode, "belago": belago_encode, "renshi": renshi_encode}


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    os.makedirs("/app/output", exist_ok=True)
    conn = sqlite3.connect("/data/fieldwork.db")

    # ── Extract numeral morphemes from lexicon JSON blobs ──────────────────
    morphemes = load_numeral_morphemes(conn)
    print(f"Extracted numeral morphemes for: {list(morphemes.keys())}")
    for lang, morph_map in morphemes.items():
        print(f"  {lang}: {morph_map}")

    # ── Read field observations for context ────────────────────────────────
    observations = load_observations(conn)
    numeral_obs = [o for o in observations if o["type"] == "numeral"]
    print(f"Read {len(observations)} observations ({len(numeral_obs)} numeral-related)")

    # ── Detect corrupted training entries ───────────────────────────────────
    errors = []
    for row in conn.execute("SELECT id, language, number, word_form FROM training ORDER BY id"):
        id_, lang, number, word_form = row
        try:
            decoded = DECODERS[lang](word_form)
            if decoded != number:
                correct_word = ENCODERS[lang](number)
                errors.append({
                    "id": id_,
                    "language": lang,
                    "number": number,
                    "wrong_word": word_form,
                    "correct_word": correct_word
                })
        except (KeyError, ValueError):
            correct_word = ENCODERS[lang](number)
            errors.append({
                "id": id_,
                "language": lang,
                "number": number,
                "wrong_word": word_form,
                "correct_word": correct_word
            })

    errors.sort(key=lambda e: e["id"])
    print(f"Detected {len(errors)} corrupted entries: IDs {[e['id'] for e in errors]}")

    # ── Write errors.json ──────────────────────────────────────────────────
    with open("/app/output/errors.json", "w") as f:
        json.dump(errors, f, indent=2)

    # ── Write fix.sql ──────────────────────────────────────────────────────
    with open("/app/output/fix.sql", "w") as f:
        for err in errors:
            cw = err["correct_word"].replace("'", "''")
            f.write(f"UPDATE training SET word_form = '{cw}' WHERE id = {err['id']};\n")

    # ── Decode test cases ──────────────────────────────────────────────────
    with open("/app/output/decode_results.tsv", "w") as out:
        for row in conn.execute("SELECT language, word_form FROM test_decode ORDER BY id"):
            lang, word = row
            number = DECODERS[lang](word)
            out.write(f"{lang}\t{word}\t{number}\n")

    # ── Encode test cases ──────────────────────────────────────────────────
    with open("/app/output/encode_results.tsv", "w") as out:
        for row in conn.execute("SELECT language, number FROM test_encode ORDER BY id"):
            lang, number = row
            word = ENCODERS[lang](number)
            out.write(f"{lang}\t{number}\t{word}\n")

    # ── Cross-system translation ───────────────────────────────────────────
    with open("/app/output/cross_results.tsv", "w") as out:
        for row in conn.execute("SELECT source_language, source_word, target_language FROM test_cross ORDER BY id"):
            src_lang, src_word, tgt_lang = row
            decimal = DECODERS[src_lang](src_word)
            tgt_word = ENCODERS[tgt_lang](decimal)
            out.write(f"{src_lang}\t{src_word}\t{tgt_lang}\t{tgt_word}\n")

    conn.close()
    print("Solution complete — all output written to /app/output/")


if __name__ == "__main__":
    main()
