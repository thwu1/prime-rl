#!/usr/bin/env python3
"""
Fix the four bugs in /app/custom_recognizers.py by targeted patching.

Bug 1: CustomDeTaxIdRecognizer has supported_language="de" but the pipeline
       analyzes with language="en". The registry filters by language, so this
       recognizer is silently excluded. Fix: change to "en".

Bug 2: CustomIbanRecognizer.validate_result rearranges the IBAN incorrectly.
       It does iban[-4:] + iban[:-4] (last 4 to front) but the Mod-97 spec
       requires iban[4:] + iban[:4] (first 4 to end). Fix: correct the slice.

Bug 3: CustomItFiscalCodeRecognizer.validate_result uses EVEN_VALUES for
       0-indexed even positions (1-indexed odd) and ODD_VALUES for 0-indexed
       odd positions (1-indexed even). The spec is the reverse: 1-indexed odd
       positions use ODD_VALUES, 1-indexed even positions use EVEN_VALUES.
       Fix: swap the table references.

Bug 4: CustomDeHealthInsuranceRecognizer.validate_result uses multiplier
       sequence [2,1,2,1,...] but the GKV spec requires [1,2,1,2,...].
       Fix: correct the sequence.
"""


def apply_fixes():
    path = "/app/custom_recognizers.py"
    with open(path, "r") as f:
        code = f.read()

    # Bug 1: Fix language mismatch for DE_TAX_ID recognizer
    # The recognizer is registered for "de" but pipeline uses language="en"
    code = code.replace(
        '''            supported_entity="DE_TAX_ID",
            supported_language="de",''',
        '''            supported_entity="DE_TAX_ID",
            supported_language="en",''',
    )

    # Bug 2: Fix IBAN rearrangement direction
    # Spec: move first 4 chars (country code + check digits) to the end
    code = code.replace(
        "rearranged = iban[-4:] + iban[:-4]",
        "rearranged = iban[4:] + iban[:4]",
    )

    # Bug 3: Fix Italian fiscal code table selection
    # 0-indexed even (1-indexed odd) should use ODD_VALUES
    # 0-indexed odd (1-indexed even) should use EVEN_VALUES
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

    # Bug 4: Fix GKV multiplier sequence
    # Spec: [1, 2, 1, 2, ...] not [2, 1, 2, 1, ...]
    code = code.replace(
        "multipliers = [2, 1, 2, 1, 2, 1, 2, 1, 2, 1]",
        "multipliers = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]",
    )

    with open(path, "w") as f:
        f.write(code)

    print("Applied 4 fixes to custom_recognizers.py")


if __name__ == "__main__":
    apply_fixes()
