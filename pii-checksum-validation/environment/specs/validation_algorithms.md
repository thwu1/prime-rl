# PII Validation Algorithm Specifications

## 1. CREDIT_CARD — Luhn Algorithm

**Format:** 13–19 digits. Cards may appear with optional space or dash separators
between 4-digit groups (e.g., `4111-1111-1111-1111` or `6011 1111 1111 1117`).
Strip all separators before validation.

**Algorithm (applied to the full digit string):**

1. Starting from the rightmost digit and moving left, double every second digit.
2. If a doubled digit exceeds 9, subtract 9 from it.
3. Sum all resulting digits.
4. The number is valid if the total modulo 10 equals 0.

---

## 2. DE_TAX_ID — ISO 7064 Mod 11,10

**Format:** Exactly 11 decimal digits (German Steueridentifikationsnummer).

**Algorithm:**

1. Set `p = 10`.
2. For each of the first 10 digits `d[i]` (left to right, i = 0..9):
   - `s = (d[i] + p) mod 10`
   - If `s == 0`, set `s = 10`
   - `p = (2 × s) mod 11`
3. `check_digit = (11 - p) mod 10`
4. The number is valid if the 11th digit equals `check_digit`.

---

## 3. DE_HEALTH_INSURANCE — GKV-Spitzenverband Prüfziffer

**Format:** 1 uppercase letter followed by 9 digits, totaling 10 characters
(German Krankenversicherungsnummer / KVNR printed on the eGK).

**Algorithm:**

1. Convert the leading letter to its 2-digit alphabetical ordinal:
   A → 01, B → 02, C → 03, …, Z → 26.
2. Prepend these two digits to the next 8 digits from the number,
   producing a 10-digit sequence.
3. Multiply each digit by alternating factors `[1, 2, 1, 2, 1, 2, 1, 2, 1, 2]`.
4. For any product ≥ 10, replace it with its **digit sum** (Quersumme),
   e.g., 12 → 1 + 2 = 3; 18 → 1 + 8 = 9.
5. Sum all ten results.
6. `check_digit = sum mod 10`.
7. The number is valid if the 10th character (the last digit) equals `check_digit`.

---

## 4. IBAN_CODE — ISO 13616 Mod-97

**Format:** 2 uppercase letters (country code) followed by 2 check digits followed
by up to 30 alphanumeric characters (BBAN). Total length 15–34 characters.
IBANs in the corpus appear without spaces.

**Algorithm:**

1. Move the first 4 characters (country code + check digits) to the end of the string.
2. Replace each letter with its numeric value: A = 10, B = 11, …, Z = 35.
   Digits remain unchanged.
3. Interpret the resulting string as an integer and compute `integer mod 97`.
4. The IBAN is valid if the result equals 1.

**Tip:** Use iterative modular arithmetic to avoid big-integer overflow:
process the numeric string left to right, maintaining a running
`remainder = (remainder × 10 + next_digit) mod 97`.

---

## 5. IT_FISCAL_CODE — Italian Codice Fiscale Check Character

**Format:** 16 characters: 6 uppercase letters, 2 digits, 1 uppercase letter,
2 digits, 1 uppercase letter, 3 digits, 1 uppercase check letter.

**Algorithm:**

Characters are numbered 1–15 (the first 15) plus the 16th check character.
Positions are classified as **odd** (1, 3, 5, …, 15) and **even** (2, 4, 6, …, 14).

**Even-position value table** (for digits and letters):

| Char | Val | Char | Val | Char | Val | Char | Val |
|------|-----|------|-----|------|-----|------|-----|
| 0    | 0   | 1    | 1   | 2    | 2   | 3    | 3   |
| 4    | 4   | 5    | 5   | 6    | 6   | 7    | 7   |
| 8    | 8   | 9    | 9   | A    | 0   | B    | 1   |
| C    | 2   | D    | 3   | E    | 4   | F    | 5   |
| G    | 6   | H    | 7   | I    | 8   | J    | 9   |
| K    | 10  | L    | 11  | M    | 12  | N    | 13  |
| O    | 14  | P    | 15  | Q    | 16  | R    | 17  |
| S    | 18  | T    | 19  | U    | 20  | V    | 21  |
| W    | 22  | X    | 23  | Y    | 24  | Z    | 25  |

**Odd-position value table:**

| Char | Val | Char | Val | Char | Val | Char | Val |
|------|-----|------|-----|------|-----|------|-----|
| 0    | 1   | 1    | 0   | 2    | 5   | 3    | 7   |
| 4    | 9   | 5    | 13  | 6    | 15  | 7    | 17  |
| 8    | 19  | 9    | 21  | A    | 1   | B    | 0   |
| C    | 5   | D    | 7   | E    | 9   | F    | 13  |
| G    | 15  | H    | 17  | I    | 19  | J    | 21  |
| K    | 2   | L    | 4   | M    | 18  | N    | 20  |
| O    | 11  | P    | 3   | Q    | 6   | R    | 8   |
| S    | 12  | T    | 14  | U    | 16  | V    | 10  |
| W    | 22  | X    | 25  | Y    | 24  | Z    | 23  |

**Steps:**

1. For each of the first 15 characters, look up its value in the
   **odd** or **even** table according to its 1-based position.
2. Sum all 15 values.
3. `check_letter = chr(sum mod 26 + ord('A'))`.
4. The code is valid if the 16th character equals `check_letter`.
