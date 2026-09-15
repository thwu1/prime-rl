#!/usr/bin/env python3
"""
PII Scanner — detects and validates PII entities from multiple countries.

Implements five checksum/validation algorithms:
  1. Luhn (credit cards)
  2. ISO 7064 Mod 11,10 (German Tax ID)
  3. GKV-Spitzenverband Prüfziffer (German Health Insurance)
  4. IBAN Mod-97 (International Bank Account Numbers)
  5. Italian Codice Fiscale check character
"""

import json
import os
import re


# ---------------------------------------------------------------------------
# 1. CREDIT_CARD — Luhn Algorithm
# ---------------------------------------------------------------------------
def luhn_validate(number_str: str) -> bool:
    """Validate a credit card number using the Luhn algorithm."""
    if not number_str.isdigit() or len(number_str) < 13 or len(number_str) > 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(number_str)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---------------------------------------------------------------------------
# 2. DE_TAX_ID — ISO 7064 Mod 11,10
# ---------------------------------------------------------------------------
def iso7064_mod11_10_validate(number_str: str) -> bool:
    """Validate an 11-digit German Tax ID using ISO 7064 Mod 11,10."""
    if not number_str.isdigit() or len(number_str) != 11:
        return False
    if number_str[0] == "0":
        return False
    p = 10
    for i in range(10):
        s = (int(number_str[i]) + p) % 10
        if s == 0:
            s = 10
        p = (2 * s) % 11
    check_digit = (11 - p) % 10
    return check_digit == int(number_str[10])


# ---------------------------------------------------------------------------
# 3. DE_HEALTH_INSURANCE — GKV-Spitzenverband Prüfziffer
# ---------------------------------------------------------------------------
def gkv_validate(kvnr: str) -> bool:
    """Validate a German KVNR using the GKV Prüfziffer algorithm."""
    kvnr = kvnr.upper()
    if len(kvnr) != 10:
        return False
    if not kvnr[0].isalpha() or not kvnr[1:].isdigit():
        return False

    # Convert letter to 2-digit ordinal: A=01 ... Z=26
    letter_ordinal = ord(kvnr[0]) - ord("A") + 1
    digits = [letter_ordinal // 10, letter_ordinal % 10]
    digits.extend(int(c) for c in kvnr[1:9])

    # Alternating multipliers [1,2,1,2,...] applied to 10 digits
    multipliers = [1, 2] * 5
    total = 0
    for d, m in zip(digits, multipliers):
        product = d * m
        # Quersumme for products >= 10
        if product >= 10:
            product = (product // 10) + (product % 10)
        total += product

    check_digit = total % 10
    return check_digit == int(kvnr[9])


# ---------------------------------------------------------------------------
# 4. IBAN_CODE — ISO 13616 Mod-97
# ---------------------------------------------------------------------------
def iban_validate(iban: str) -> bool:
    """Validate an IBAN using the Mod-97 algorithm."""
    iban = iban.upper().replace(" ", "").replace("-", "")
    if len(iban) < 15 or len(iban) > 34:
        return False
    if not iban[:2].isalpha() or not iban[2:4].isdigit():
        return False

    # Rearrange: move first 4 chars to end
    rearranged = iban[4:] + iban[:4]

    # Convert letters to numeric values and compute mod 97 iteratively
    remainder = 0
    for ch in rearranged:
        if ch.isdigit():
            remainder = (remainder * 10 + int(ch)) % 97
        else:
            val = ord(ch) - ord("A") + 10  # A=10, B=11, ..., Z=35
            # Two-digit value, so multiply remainder by 100
            remainder = (remainder * 100 + val) % 97

    return remainder == 1


# ---------------------------------------------------------------------------
# 5. IT_FISCAL_CODE — Italian Codice Fiscale check character
# ---------------------------------------------------------------------------
_IT_EVEN_VALUES = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
    "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "A": 0, "B": 1, "C": 2, "D": 3, "E": 4,
    "F": 5, "G": 6, "H": 7, "I": 8, "J": 9,
    "K": 10, "L": 11, "M": 12, "N": 13, "O": 14,
    "P": 15, "Q": 16, "R": 17, "S": 18, "T": 19,
    "U": 20, "V": 21, "W": 22, "X": 23, "Y": 24, "Z": 25,
}

_IT_ODD_VALUES = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9,
    "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
    "A": 1, "B": 0, "C": 5, "D": 7, "E": 9,
    "F": 13, "G": 15, "H": 17, "I": 19, "J": 21,
    "K": 2, "L": 4, "M": 18, "N": 20, "O": 11,
    "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14,
    "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
}

_IT_FC_PATTERN = re.compile(r"^[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]$")


def it_fiscal_code_validate(code: str) -> bool:
    """Validate an Italian Codice Fiscale check character."""
    code = code.upper()
    if len(code) != 16 or not _IT_FC_PATTERN.match(code):
        return False

    total = 0
    for i in range(15):
        ch = code[i]
        if i % 2 == 0:
            # 0-indexed even → 1-indexed odd position
            total += _IT_ODD_VALUES[ch]
        else:
            # 0-indexed odd → 1-indexed even position
            total += _IT_EVEN_VALUES[ch]

    expected_check = chr(total % 26 + ord("A"))
    return code[15] == expected_check


# ---------------------------------------------------------------------------
# Entity detection patterns
# ---------------------------------------------------------------------------
ENTITY_PATTERNS = [
    (
        "CREDIT_CARD",
        re.compile(r"\b(\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4})\b"),
        lambda val: luhn_validate(re.sub(r"[\s-]", "", val)),
        lambda val: re.sub(r"[\s-]", "", val),
    ),
    (
        "DE_TAX_ID",
        re.compile(r"\b(\d{11})\b"),
        iso7064_mod11_10_validate,
        lambda val: val,
    ),
    (
        "DE_HEALTH_INSURANCE",
        re.compile(r"\b([A-Za-z]\d{9})\b"),
        gkv_validate,
        lambda val: val.upper(),
    ),
    (
        "IBAN_CODE",
        re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{11,30})\b"),
        iban_validate,
        lambda val: val.upper(),
    ),
    (
        "IT_FISCAL_CODE",
        re.compile(r"\b([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])\b"),
        it_fiscal_code_validate,
        lambda val: val.upper(),
    ),
]


def scan_file(filepath: str) -> list:
    """Scan a text file for PII entities, validate, and return detections."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    detections = []
    seen = set()

    for entity_type, pattern, validator, normalizer in ENTITY_PATTERNS:
        for match in pattern.finditer(text):
            raw_value = match.group(1)
            normalized = normalizer(raw_value)
            if validator(normalized):
                key = (entity_type, normalized)
                if key not in seen:
                    seen.add(key)
                    detections.append({"type": entity_type, "value": normalized})

    detections.sort(key=lambda d: (d["type"], d["value"]))
    return detections


def main():
    corpus_path = "/app/corpus/records.txt"
    output_path = "/app/output/detections.json"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    detections = scan_file(corpus_path)

    with open(output_path, "w") as f:
        json.dump({"detections": detections}, f, indent=2)

    print(f"Detected {len(detections)} valid PII entities.")
    for d in detections:
        print(f"  {d['type']}: {d['value']}")


if __name__ == "__main__":
    main()
