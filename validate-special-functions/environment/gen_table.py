#!/usr/bin/env python3
"""Generate reference table of special function values with specific corruptions."""
import json
from mpmath import mp, mpf, gamma, besselj, airyai, airybi, nstr

mp.dps = 60


def corrupt_value(value_str, error_type):
    """Introduce a specific type of error into a value string."""
    if error_type == "sign_flip":
        if value_str.startswith('-'):
            return value_str[1:]
        else:
            return '-' + value_str
    elif error_type == "digit_swap_10":
        dot = value_str.index('.')
        pos = dot + 10
        chars = list(value_str)
        if pos + 1 < len(chars):
            chars[pos], chars[pos + 1] = chars[pos + 1], chars[pos]
        return ''.join(chars)
    elif error_type == "perturb_18":
        dot = value_str.index('.')
        pos = dot + 18
        chars = list(value_str)
        if pos < len(chars):
            d = int(chars[pos])
            chars[pos] = str((d + 3) % 10)
        return ''.join(chars)
    elif error_type == "perturb_14":
        dot = value_str.index('.')
        pos = dot + 14
        chars = list(value_str)
        if pos < len(chars):
            d = int(chars[pos])
            chars[pos] = str((d + 3) % 10)
        return ''.join(chars)
    elif error_type == "perturb_26":
        dot = value_str.index('.')
        pos = dot + 26
        chars = list(value_str)
        for i in range(min(6, len(chars) - pos)):
            d = int(chars[pos + i])
            chars[pos + i] = str((d + 1 + i) % 10)
        return ''.join(chars)
    return value_str


def main():
    entries_spec = [
        ("gamma_1_3", "Gamma", "z=1/3", gamma(mpf(1) / 3)),
        ("gamma_2_3", "Gamma", "z=2/3", gamma(mpf(2) / 3)),
        ("gamma_1_4", "Gamma", "z=1/4", gamma(mpf(1) / 4)),
        ("gamma_3_4", "Gamma", "z=3/4", gamma(mpf(3) / 4)),
        ("ai_1", "AiryAi", "x=1", airyai(mpf(1))),
        ("ai_prime_1", "AiryAi'", "x=1", airyai(mpf(1), derivative=1)),
        ("bi_1", "AiryBi", "x=1", airybi(mpf(1))),
        ("bi_prime_1", "AiryBi'", "x=1", airybi(mpf(1), derivative=1)),
        ("ai_2", "AiryAi", "x=2", airyai(mpf(2))),
        ("ai_prime_2", "AiryAi'", "x=2", airyai(mpf(2), derivative=1)),
        ("bi_2", "AiryBi", "x=2", airybi(mpf(2))),
        ("bi_prime_2", "AiryBi'", "x=2", airybi(mpf(2), derivative=1)),
        ("j0_1", "BesselJ", "n=0,x=1", besselj(0, mpf(1))),
        ("j1_1", "BesselJ", "n=1,x=1", besselj(1, mpf(1))),
        ("j2_1", "BesselJ", "n=2,x=1", besselj(2, mpf(1))),
        ("j0_10", "BesselJ", "n=0,x=10", besselj(0, mpf(10))),
        ("ai_0", "AiryAi", "x=0", airyai(mpf(0))),
        ("bi_0", "AiryBi", "x=0", airybi(mpf(0))),
        ("ai_prime_0", "AiryAi'", "x=0", airyai(mpf(0), derivative=1)),
        ("bi_prime_0", "AiryBi'", "x=0", airybi(mpf(0), derivative=1)),
    ]

    corruptions = {
        "gamma_2_3": "perturb_26",
        "bi_1": "perturb_18",
        "ai_prime_2": "perturb_14",
        "j0_10": "sign_flip",
        "ai_prime_0": "digit_swap_10",
    }

    result = []
    for id_, func, params, value in entries_spec:
        value_str = nstr(value, 52, strip_zeros=False)
        if id_ in corruptions:
            value_str = corrupt_value(value_str, corruptions[id_])
        result.append({
            "id": id_,
            "function": func,
            "parameters": params,
            "claimed_value": value_str
        })

    with open("/app/reference_table.json", "w") as f:
        json.dump({
            "description": "Reference table of special function values. All values claimed correct to 50 decimal digits.",
            "claimed_precision_digits": 50,
            "entries": result
        }, f, indent=2)

    print(f"Generated reference table with {len(result)} entries")


if __name__ == "__main__":
    main()
