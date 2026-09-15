"""Custom PatternRecognizer subclasses for multi-country PII detection."""

from presidio_analyzer import EntityRecognizer, Pattern, PatternRecognizer


class CustomCreditCardRecognizer(PatternRecognizer):
    """Credit card numbers validated with Luhn checksum."""

    PATTERNS = [
        Pattern(
            "credit_card",
            r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b",
            0.5,
        ),
    ]
    CONTEXT = ["credit", "card", "payment", "visa", "mastercard"]

    def __init__(self):
        super().__init__(
            supported_entity="CREDIT_CARD",
            supported_language="en",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            name="CustomCreditCardRecognizer",
        )
        self._replacement_pairs = [("-", ""), (" ", "")]

    def validate_result(self, pattern_text):
        sanitized = EntityRecognizer.sanitize_value(
            pattern_text, self._replacement_pairs
        )
        if not sanitized.isdigit() or len(sanitized) < 13 or len(sanitized) > 19:
            return False
        digits = [int(d) for d in sanitized]
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        total = sum(odd_digits)
        for d in even_digits:
            total += sum(int(c) for c in str(d * 2))
        return total % 10 == 0


class CustomDeTaxIdRecognizer(PatternRecognizer):
    """German Steueridentifikationsnummer validated with ISO 7064 Mod 11,10."""

    PATTERNS = [
        Pattern("de_tax_id", r"\b(\d{11})\b", 0.3),
    ]
    CONTEXT = ["steuer", "idnr", "identifikationsnummer", "tax"]

    def __init__(self):
        super().__init__(
            supported_entity="DE_TAX_ID",
            supported_language="de",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            name="CustomDeTaxIdRecognizer",
        )

    def validate_result(self, pattern_text):
        if len(pattern_text) != 11 or not pattern_text.isdigit():
            return False
        if pattern_text[0] == "0":
            return False
        p = 10
        for i in range(10):
            s = (int(pattern_text[i]) + p) % 10
            if s == 0:
                s = 10
            p = (2 * s) % 11
        check_digit = (11 - p) % 10
        return check_digit == int(pattern_text[10])


class CustomIbanRecognizer(PatternRecognizer):
    """International Bank Account Numbers validated with Mod-97."""

    PATTERNS = [
        Pattern("iban", r"\b([A-Z]{2}\d{2}[A-Z0-9]{11,30})\b", 0.5),
    ]
    CONTEXT = ["iban", "bank", "account", "transfer"]

    def __init__(self):
        super().__init__(
            supported_entity="IBAN_CODE",
            supported_language="en",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            name="CustomIbanRecognizer",
        )

    def validate_result(self, pattern_text):
        iban = pattern_text.upper().replace(" ", "").replace("-", "")
        if len(iban) < 15 or len(iban) > 34:
            return False
        if not iban[:2].isalpha() or not iban[2:4].isdigit():
            return False

        # Rearrange: move characters for mod-97 check
        rearranged = iban[-4:] + iban[:-4]

        remainder = 0
        for ch in rearranged:
            if ch.isdigit():
                remainder = (remainder * 10 + int(ch)) % 97
            else:
                val = ord(ch) - ord("A") + 10
                remainder = (remainder * 100 + val) % 97

        return remainder == 1


class CustomItFiscalCodeRecognizer(PatternRecognizer):
    """Italian Codice Fiscale validated with check character algorithm."""

    PATTERNS = [
        Pattern(
            "it_fiscal_code",
            r"\b([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])\b",
            0.5,
        ),
    ]
    CONTEXT = ["codice", "fiscale", "fiscal"]

    EVEN_VALUES = {
        "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
        "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
        "A": 0, "B": 1, "C": 2, "D": 3, "E": 4,
        "F": 5, "G": 6, "H": 7, "I": 8, "J": 9,
        "K": 10, "L": 11, "M": 12, "N": 13, "O": 14,
        "P": 15, "Q": 16, "R": 17, "S": 18, "T": 19,
        "U": 20, "V": 21, "W": 22, "X": 23, "Y": 24, "Z": 25,
    }

    ODD_VALUES = {
        "0": 1, "1": 0, "2": 5, "3": 7, "4": 9,
        "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
        "A": 1, "B": 0, "C": 5, "D": 7, "E": 9,
        "F": 13, "G": 15, "H": 17, "I": 19, "J": 21,
        "K": 2, "L": 4, "M": 18, "N": 20, "O": 11,
        "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14,
        "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
    }

    def __init__(self):
        super().__init__(
            supported_entity="IT_FISCAL_CODE",
            supported_language="en",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            name="CustomItFiscalCodeRecognizer",
        )

    def validate_result(self, pattern_text):
        code = pattern_text.upper()
        if len(code) != 16:
            return False

        total = 0
        for i in range(15):
            ch = code[i]
            if i % 2 == 0:
                # 0-indexed even position corresponds to 1-indexed odd
                total += self.EVEN_VALUES.get(ch, 0)
            else:
                # 0-indexed odd position corresponds to 1-indexed even
                total += self.ODD_VALUES.get(ch, 0)

        expected_check = chr(total % 26 + ord("A"))
        return code[15] == expected_check


class CustomDeHealthInsuranceRecognizer(PatternRecognizer):
    """German KVNR validated with GKV-Spitzenverband Pruefziffer algorithm."""

    PATTERNS = [
        Pattern("de_kvnr", r"\b([A-Z]\d{9})\b", 0.3),
    ]
    CONTEXT = ["kvnr", "krankenversicherung", "versichertennummer", "versicherung"]

    def __init__(self):
        super().__init__(
            supported_entity="DE_HEALTH_INSURANCE",
            supported_language="en",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            name="CustomDeHealthInsuranceRecognizer",
        )

    def validate_result(self, pattern_text):
        kvnr = pattern_text.upper()
        if len(kvnr) != 10 or not kvnr[0].isalpha() or not kvnr[1:].isdigit():
            return False

        letter_ordinal = ord(kvnr[0]) - ord("A") + 1
        digits = [letter_ordinal // 10, letter_ordinal % 10]
        digits.extend(int(c) for c in kvnr[1:9])

        # Alternating multipliers applied to the 10-digit sequence
        multipliers = [2, 1, 2, 1, 2, 1, 2, 1, 2, 1]

        total = 0
        for d, m in zip(digits, multipliers):
            product = d * m
            if product >= 10:
                product = (product // 10) + (product % 10)
            total += product

        check_digit = total % 10
        return check_digit == int(kvnr[9])
