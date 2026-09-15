#!/usr/bin/env python3
"""Fix recognizer bugs, implement format-preserving anonymization, patch pipeline.

This script:
1. Fixes 4 bugs in /app/custom_recognizers.py
2. Writes /app/anonymizers.py with format-preserving operators
3. Patches /app/pipeline.py to use the anonymization module
"""

import textwrap


def fix_recognizers():
    """Apply four targeted fixes to custom_recognizers.py."""
    path = "/app/custom_recognizers.py"
    with open(path, "r") as f:
        code = f.read()

    # Bug 1: DE_TAX_ID recognizer has supported_language="de" but the
    # pipeline analyzes with language="en", so the registry silently
    # excludes it. Fix: change to "en".
    code = code.replace(
        '            supported_entity="DE_TAX_ID",\n'
        '            supported_language="de",',
        '            supported_entity="DE_TAX_ID",\n'
        '            supported_language="en",',
    )

    # Bug 2: IBAN rearrangement is backwards.
    # Code does iban[-4:]+iban[:-4] (last 4 to front).
    # Spec says: move first 4 chars to the end → iban[4:]+iban[:4].
    code = code.replace(
        "rearranged = iban[-4:] + iban[:-4]",
        "rearranged = iban[4:] + iban[:4]",
    )

    # Bug 3: Italian fiscal code lookup table references are swapped.
    # In the code, 0-indexed even positions (which are 1-indexed ODD)
    # use EVEN_VALUES, but the spec says odd positions use ODD_VALUES.
    code = code.replace(
        "total += self.EVEN_VALUES.get(ch, 0)\n"
        "            else:\n"
        "                # 0-indexed odd position corresponds to 1-indexed even\n"
        "                total += self.ODD_VALUES.get(ch, 0)",
        "total += self.ODD_VALUES.get(ch, 0)\n"
        "            else:\n"
        "                # 0-indexed odd position corresponds to 1-indexed even\n"
        "                total += self.EVEN_VALUES.get(ch, 0)",
    )

    # Bug 4: GKV multiplier sequence is [2,1,2,1,...] but spec says [1,2,1,2,...].
    code = code.replace(
        "multipliers = [2, 1, 2, 1, 2, 1, 2, 1, 2, 1]",
        "multipliers = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]",
    )

    with open(path, "w") as f:
        f.write(code)
    print("Fixed 4 bugs in custom_recognizers.py")


def write_anonymizers():
    """Write /app/anonymizers.py with format-preserving operators."""
    code = textwrap.dedent('''\
        """Format-preserving anonymization operators for five PII entity types.

        Each operator generates a replacement value that:
        - Passes the same checksum algorithm as the original
        - Has the same length and structural format
        - Is different from the original
        - Is deterministic given the same seed
        """
        import random
        import re


        # ---- Lookup tables for Italian fiscal code ----

        ODD_VALUES = {
            "0": 1, "1": 0, "2": 5, "3": 7, "4": 9,
            "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
            "A": 1, "B": 0, "C": 5, "D": 7, "E": 9,
            "F": 13, "G": 15, "H": 17, "I": 19, "J": 21,
            "K": 2, "L": 4, "M": 18, "N": 20, "O": 11,
            "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14,
            "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
        }

        EVEN_VALUES = {
            "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
            "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
            "A": 0, "B": 1, "C": 2, "D": 3, "E": 4,
            "F": 5, "G": 6, "H": 7, "I": 8, "J": 9,
            "K": 10, "L": 11, "M": 12, "N": 13, "O": 14,
            "P": 15, "Q": 16, "R": 17, "S": 18, "T": 19,
            "U": 20, "V": 21, "W": 22, "X": 23, "Y": 24, "Z": 25,
        }


        def anonymize_credit_card(value, rng):
            """Generate a Luhn-valid replacement with same length."""
            digits = [int(d) for d in value]
            n = len(digits)
            # Keep first digit (card network), randomize middle digits
            payload = [digits[0]]
            for _ in range(1, n - 1):
                payload.append(rng.randint(0, 9))
            # Compute Luhn check digit
            # In the full number, check digit is rightmost.
            # Double every second digit from the right, starting at position 2 from right.
            total = 0
            for i, d in enumerate(reversed(payload)):
                if i % 2 == 0:
                    d2 = d * 2
                    if d2 > 9:
                        d2 -= 9
                    total += d2
                else:
                    total += d
            check = (10 - total % 10) % 10
            result = "".join(str(d) for d in payload) + str(check)
            if result == value:
                # Extremely unlikely but handle: change one inner digit and recompute
                payload[1] = (payload[1] + 1) % 10
                total = 0
                for i, d in enumerate(reversed(payload)):
                    if i % 2 == 0:
                        d2 = d * 2
                        if d2 > 9:
                            d2 -= 9
                        total += d2
                    else:
                        total += d
                check = (10 - total % 10) % 10
                result = "".join(str(d) for d in payload) + str(check)
            return result


        def anonymize_iban(value, rng):
            """Generate a Mod-97-valid IBAN with same country code and length."""
            country = value[:2]
            bban = value[4:]
            # Randomize BBAN preserving character types (digits stay digits, letters stay letters)
            new_bban_chars = []
            for c in bban:
                if c.isdigit():
                    new_bban_chars.append(str(rng.randint(0, 9)))
                elif c.isalpha():
                    new_bban_chars.append(chr(rng.randint(0, 25) + ord("A")))
            new_bban = "".join(new_bban_chars)
            # Compute Mod-97 check digits
            temp = new_bban + country + "00"
            numeric = "".join(
                str(ord(c) - 55) if c.isalpha() else c for c in temp
            )
            remainder = int(numeric) % 97
            check = 98 - remainder
            result = f"{country}{check:02d}{new_bban}"
            if result == value:
                new_bban_chars[0] = str((int(new_bban_chars[0]) + 1) % 10) if new_bban_chars[0].isdigit() else chr((ord(new_bban_chars[0]) - ord("A") + 1) % 26 + ord("A"))
                new_bban = "".join(new_bban_chars)
                temp = new_bban + country + "00"
                numeric = "".join(
                    str(ord(c) - 55) if c.isalpha() else c for c in temp
                )
                remainder = int(numeric) % 97
                check = 98 - remainder
                result = f"{country}{check:02d}{new_bban}"
            return result


        def anonymize_tax_id(value, rng):
            """Generate an ISO 7064 Mod 11,10-valid 11-digit ID."""
            # Generate 10 random digits (first digit non-zero per German tax ID rules)
            payload = [rng.randint(1, 9)]
            for _ in range(9):
                payload.append(rng.randint(0, 9))
            # Compute check digit using iterative ISO 7064 Mod 11,10
            p = 10
            for d in payload:
                s = (p + d) % 10
                if s == 0:
                    s = 10
                p = (s * 2) % 11
            check = (11 - p) % 10
            result = "".join(str(d) for d in payload) + str(check)
            if result == value:
                payload[1] = (payload[1] + 1) % 10
                p = 10
                for d in payload:
                    s = (p + d) % 10
                    if s == 0:
                        s = 10
                    p = (s * 2) % 11
                check = (11 - p) % 10
                result = "".join(str(d) for d in payload) + str(check)
            return result


        def anonymize_fiscal_code(value, rng):
            """Generate a valid Italian Codice Fiscale with correct check character."""
            consonants = "BCDFGHJKLMNPQRSTVWXYZ"
            month_codes = "ABCDEHLMPRST"
            # Generate structural components
            surname = "".join(rng.choice(consonants) for _ in range(3))
            name = "".join(rng.choice(consonants) for _ in range(3))
            year = f"{rng.randint(0, 99):02d}"
            month = rng.choice(month_codes)
            day = f"{rng.randint(1, 31):02d}"
            mun_letter = chr(rng.randint(0, 25) + ord("A"))
            mun_num = f"{rng.randint(0, 999):03d}"
            chars_15 = surname + name + year + month + day + mun_letter + mun_num
            # Compute check character
            total = 0
            for i, c in enumerate(chars_15):
                if (i + 1) % 2 == 1:
                    total += ODD_VALUES[c]
                else:
                    total += EVEN_VALUES[c]
            check = chr(total % 26 + ord("A"))
            result = chars_15 + check
            if result == value:
                # Change one consonant and recompute
                new_s = (consonants.index(surname[0]) + 1) % len(consonants)
                surname = consonants[new_s] + surname[1:]
                chars_15 = surname + name + year + month + day + mun_letter + mun_num
                total = 0
                for i, c in enumerate(chars_15):
                    if (i + 1) % 2 == 1:
                        total += ODD_VALUES[c]
                    else:
                        total += EVEN_VALUES[c]
                check = chr(total % 26 + ord("A"))
                result = chars_15 + check
            return result


        def anonymize_gkv(value, rng):
            """Generate a valid GKV health insurance number (letter + 9 digits)."""
            letter = chr(rng.randint(0, 25) + ord("A"))
            lv = ord(letter) - ord("A") + 1
            inner = [rng.randint(0, 9) for _ in range(8)]
            # Compute check digit
            all_digits = [lv // 10, lv % 10] + inner
            mults = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]
            total = 0
            for i in range(10):
                p = all_digits[i] * mults[i]
                total += (p // 10 + p % 10) if p >= 10 else p
            check = total % 10
            result = letter + "".join(str(d) for d in inner) + str(check)
            if result == value:
                inner[0] = (inner[0] + 1) % 10
                all_digits = [lv // 10, lv % 10] + inner
                total = 0
                for i in range(10):
                    p = all_digits[i] * mults[i]
                    total += (p // 10 + p % 10) if p >= 10 else p
                check = total % 10
                result = letter + "".join(str(d) for d in inner) + str(check)
            return result


        ANONYMIZERS = {
            "CREDIT_CARD": anonymize_credit_card,
            "IBAN_CODE": anonymize_iban,
            "DE_TAX_ID": anonymize_tax_id,
            "IT_FISCAL_CODE": anonymize_fiscal_code,
            "DE_HEALTH_INSURANCE": anonymize_gkv,
        }


        def anonymize(text, detection_records, seed=42):
            """Apply format-preserving anonymization to all detected PII.

            Returns (anonymized_text, updated_detection_records).
            """
            rng = random.Random(seed)
            # Sort detections by start position (descending) to replace from end to start
            sorted_dets = sorted(detection_records, key=lambda d: d["start"], reverse=True)
            anonymized_text = text
            for d in sorted_dets:
                et = d["entity_type"]
                orig = d["original_value"]
                operator = ANONYMIZERS[et]
                anon_value = operator(orig, rng)
                d["anonymized_value"] = anon_value
                # Replace in text, preserving any formatting (dashes/spaces)
                start, end = d["start"], d["end"]
                raw_span = text[start:end]
                # Rebuild the span with the anonymized value, preserving separators
                new_span = _rebuild_span(raw_span, anon_value)
                anonymized_text = anonymized_text[:start] + new_span + anonymized_text[end:]
            return anonymized_text, detection_records


        def _rebuild_span(raw_span, clean_value):
            """Insert the clean anonymized value back into the original span format.

            Preserves dashes and spaces at their original positions.
            """
            result = []
            clean_idx = 0
            for c in raw_span:
                if c in ("-", " "):
                    result.append(c)
                else:
                    if clean_idx < len(clean_value):
                        result.append(clean_value[clean_idx])
                        clean_idx += 1
                    else:
                        result.append(c)
            # Append any remaining clean_value characters
            while clean_idx < len(clean_value):
                result.append(clean_value[clean_idx])
                clean_idx += 1
            return "".join(result)
    ''')
    with open("/app/anonymizers.py", "w") as f:
        f.write(code)
    print("Wrote /app/anonymizers.py")


def patch_pipeline():
    """Patch /app/pipeline.py to use anonymizers module."""
    path = "/app/pipeline.py"
    with open(path, "r") as f:
        code = f.read()

    # Replace the NotImplementedError anonymize function with an import
    old_func = '''def anonymize(text, detection_records, seed=42):
    """Apply format-preserving anonymization to detected PII values.

    Each replacement value must:
    - Pass the same checksum/validation algorithm as the original
    - Preserve the format (same length, same structural pattern)
    - Be different from the original
    - Be deterministic (same seed produces same output)

    Args:
        text: Original corpus text
        detection_records: List of dicts with entity_type, start, end, score, original_value
        seed: Random seed for deterministic output

    Returns:
        Tuple of (anonymized_text, updated_detection_records_with_anonymized_values)

    TODO: Implement format-preserving anonymization operators for:
    - CREDIT_CARD: generate replacement digits, recompute Luhn check digit
    - IBAN_CODE: preserve country code, randomize BBAN, recompute Mod-97 check digits
    - DE_TAX_ID: generate 10 random digits, compute ISO 7064 Mod 11,10 check digit
    - IT_FISCAL_CODE: generate valid structural components, compute check character
    - DE_HEALTH_INSURANCE: generate letter + 8 digits, compute GKV check digit
    """
    raise NotImplementedError(
        "Format-preserving anonymization not yet implemented. "
        "Implement operators for each entity type that generate "
        "replacement values passing the same checksum algorithms."
    )'''

    new_func = '''def anonymize(text, detection_records, seed=42):
    """Apply format-preserving anonymization using operators from anonymizers module."""
    from anonymizers import anonymize as _anonymize
    return _anonymize(text, detection_records, seed)'''

    code = code.replace(old_func, new_func)

    with open(path, "w") as f:
        f.write(code)
    print("Patched /app/pipeline.py")


if __name__ == "__main__":
    fix_recognizers()
    write_anonymizers()
    patch_pipeline()
