A stripped ELF binary at `/app/cipher_module` implements a proprietary block cipher. An automated security scanner flagged potential weaknesses in its substitution layer, but the results were never verified by a human analyst. The scanner output is at `/app/scan_report.txt`.

Conduct a manual security evaluation of the cipher's substitution components. Determine whether the automated findings represent genuine cryptographic vulnerabilities or scanner false positives. If the substitution layer is genuinely weak, identify the simplest single permutation — the most elementary function from which the cipher's substitution tables could have been derived.

Write your assessment to `/app/report.json`:

    {
        "vulnerable": true or false,
        "core_permutation": [p0, p1, ..., p255] or null
    }

When vulnerable, `core_permutation` must be a permutation of integers 0 through 255 representing the irreducible algebraic core shared by all substitution tables in the binary. When not vulnerable, use `null`.