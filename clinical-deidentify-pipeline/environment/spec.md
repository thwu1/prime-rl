# De-identification Specification

## PHI Categories

The clinical documents contain the following types of Protected Health Information to detect and redact:

| Tag | Description |
|-----|-------------|
| `naam` | Person names — patients, doctors, and third parties, including first names, surnames, initials, titles |
| `bsn` | Burgerservicenummer — Dutch citizen identification number (9 digits, requires checksum validation) |
| `datum` | Dates in any format (numeric and Dutch-language) |
| `leeftijd` | Age expressions |
| `telefoonnummer` | Phone numbers — mobile, landline, and international formats |
| `locatie` | Addresses, street names, postal codes, city/town names |
| `instelling` | Healthcare institution names |
| `email` | Email addresses |

## Key Challenges

### BSN Validation
Not every 9-digit number is a valid BSN. The Dutch government specifies an official checksum algorithm for BSN validation. Numbers that fail this check must NOT be tagged as `bsn`. The corpus contains deliberate invalid BSNs as decoys.

### Medical Term Preservation
Certain words function as both patient surnames and parts of medical terminology. The file `/app/data/medical_terms.txt` lists medical eponyms that must be preserved. The pipeline must determine from context whether a word is being used as a name (redact) or as part of a medical term (preserve).

### Dutch Naming Conventions
Dutch surnames frequently include interfixes (tussenvoegsels) such as "van", "van der", "de", forming multi-word compound names. Hyphenated married names also occur. Patient metadata in `/app/patients.json` provides known patient name components keyed by document ID.

## Output Format

### Redacted Text (`{docname}.txt`)
PHI spans replaced with `[TAG-N]` markers where TAG is the uppercase category and N is a counter. Identical original text strings share the same counter value within a document.

### Annotations (`{docname}.annotations.json`)
JSON array of objects:
```json
[{"text": "original PHI", "start_char": 0, "end_char": 12, "tag": "naam"}]
```

## Available Reference Data

Files in `/app/data/` (one entry per line):
- `first_names.txt` — Dutch first names
- `surnames.txt` — Dutch surnames
- `interfixes.txt` — Dutch name component words (tussenvoegsels)
- `prefixes.txt` — Titles and honorifics
- `places.txt` — Dutch city and town names
- `streets.txt` — Street names
- `institutions.txt` — Healthcare institution names
- `medical_terms.txt` — Medical eponyms to preserve
