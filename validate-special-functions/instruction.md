The file `/app/reference_table.json` contains 20 special mathematical function values (Gamma, Airy, and Bessel families), each claimed to 50 decimal digits of precision. Exactly 5 of the 20 entries have been corrupted with errors ranging from sign flips to subtle perturbations deep within the digit string.

Identify every corrupted entry, provide its corrected value to at least 40 decimal digits of precision, and validate every entry — both corrupted and correct — against known mathematical properties of the functions involved. Every conclusion must be independently justified; do not rely solely on a single method.

Write your findings to `/app/audit_report.json` with this structure:

```json
{
  "summary": {"total_entries": 20, "errors_found": 5},
  "errors": [
    {
      "id": "entry_id",
      "corrected_value": "high_precision_string",
      "detected_by": {
        "identity_type": "relationship_name",
        "description": "explanation"
      }
    }
  ],
  "validated_entries": [
    {
      "id": "entry_id",
      "validation": {
        "identity_type": "relationship_name",
        "description": "explanation"
      }
    }
  ]
}
```

## Requirements

- The `errors` array must contain exactly the 5 corrupted entries; the `validated_entries` array must contain exactly the remaining 15 correct entries. Every entry in the reference table must appear in exactly one of the two arrays.
- Each corrected value must be accurate to at least 40 decimal digits relative to the true value.
- Each error entry must have a `detected_by` object with an `identity_type` string naming the specific mathematical property or method used for detection.
- Each validated entry must have a `validation` object with an `identity_type` string naming the specific mathematical property or method used for validation.

## Required identity types

The `identity_type` fields across the full report must include at minimum these three categories (using these terms in the field values):

1. **Gamma reflection formula** — the identity Gamma(z)*Gamma(1-z) = pi/sin(pi*z). The `identity_type` value must contain the word "reflection". Apply at z=1/3 (yielding Gamma(1/3)*Gamma(2/3) = 2*pi/sqrt(3)) and at z=1/4 (yielding Gamma(1/4)*Gamma(3/4) = pi*sqrt(2)).

2. **Airy Wronskian identity** — the relation Ai(x)*Bi'(x) - Ai'(x)*Bi(x) = 1/pi, which holds for all x. The `identity_type` value must contain the word "wronskian". Verify at x=0, x=1, and x=2.

3. **Bessel recurrence relation** — the three-term recurrence J_{n-1}(x) + J_{n+1}(x) = (2n/x)*J_n(x). The `identity_type` value must contain the word "bessel" or "recurrence". Verify at n=1, x=1: J_0(1) + J_2(1) = 2*J_1(1).

The corrected values you report must actually satisfy all of these identities to at least 40-digit precision; they are verified numerically, not just by label.