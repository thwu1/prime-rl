Implement `/app/section121.py` — a Python module that computes the IRC Section 121 exclusion for gain from the sale or exchange of a principal residence.

Your specification is the Catala formalization at `/app/section_121.catala_en`. This file uses the Catala domain-specific language — a literate programming language where legal statute text is interleaved with executable code blocks (fenced by ` ```catala ` and ` ```catala-metadata `). The statute text outside code fences is the authoritative legal specification. The Catala code blocks formalize most of the statutory rules but contain incomplete implementations (marked TODO) and transcription errors. Where the Catala code and statute text diverge, the statute governs.

Your implementation must faithfully encode the complete exclusion logic formalized in the Catala file, covering all return types and subsections present in the specification.

## Interface

Export a function `compute_exclusion(scenario: dict) -> dict`.

Input keys vary by `return_type`:
- `"single"`: `date_of_sale` (ISO date string), `gain` (int, dollars), `person`
- `"joint"`: `date_of_sale`, `gain`, `person1`, `person2`
- `"surviving_spouse"`: `date_of_sale`, `gain`, `survivor`, `deceased_at_death`, `date_of_death` (ISO date string)

Each person object contains:
```json
{
  "ownership_periods": [{"begin": "YYYY-MM-DD", "end": "YYYY-MM-DD"}, ...],
  "usage_periods": [{"begin": "YYYY-MM-DD", "end": "YYYY-MM-DD"}, ...],
  "prior_sale_date": null | "YYYY-MM-DD"
}
```

Output: `{"excluded_amount": <int>, "gain_cap": <int>}` — amounts in whole dollars.