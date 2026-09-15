Build a medication reconciliation pipeline at `/app/reconcile.py` that reads `/app/medications.json` and `/app/formulary.json`, then writes `/app/reconciliation_report.json`.

`/app/medications.json` contains a patient medication list. Each entry has `id`, `type` (`ndc`, `drug_name`, or `approximate`), and `value`. Resolve every entry to its canonical RxNorm concept using NLM's RxNav REST services at `https://rxnav.nlm.nih.gov/REST/`, extract clinical attributes, detect therapeutic duplications, and cross-reference against the hospital formulary.

`/app/formulary.json` lists formulary-approved medications by RxCUI. For each resolved medication, determine formulary membership and, for non-formulary items, identify formulary alternatives that share at least one active ingredient.

**Output schema** (`/app/reconciliation_report.json`):
```json
{
  "patient_id": "<from input>",
  "medications": [
    {
      "id": "<string>",
      "rxcui": "<string>",
      "name": "<canonical RxNorm name>",
      "tty": "<RxNorm term type>",
      "ingredients": [{"rxcui": "<string>", "name": "<string>"}],
      "generic_equivalent": {"rxcui": "<string>", "name": "<string>"} | null,
      "atc_classes": [{"class_id": "<string>", "class_name": "<string>"}],
      "on_formulary": "<boolean>",
      "formulary_alternatives": [{"rxcui": "<string>", "name": "<string>"}]
    }
  ],
  "therapeutic_duplications": [
    {
      "ingredient_rxcui": "<string>",
      "ingredient_name": "<string>",
      "medication_ids": ["<string>"]
    }
  ]
}
```

**Requirements:**
- Resolve each entry to an RxCUI based on its `type`. NDC codes may use segmented or normalized formats. Approximate entries contain misspellings requiring tolerant matching.
- `ingredients`: base active ingredients (TTY=IN) for each concept. Multi-ingredient products list all constituents.
- `generic_equivalent`: for branded products (SBD), the corresponding generic concept; `null` for products already generic.
- `atc_classes`: ATC therapeutic classification from the RxClass API for each medication's ingredients.
- `therapeutic_duplications`: any base ingredient appearing in two or more medications. `medication_ids` sorted ascending.
- `on_formulary`: `true` if the resolved RxCUI is in the formulary.
- `formulary_alternatives`: for non-formulary medications, formulary entries sharing at least one active ingredient; empty list for on-formulary items.
- All RxCUI values must be strings. Handle API rate limits with retry logic.

Run: `cd /app && python3 reconcile.py`
