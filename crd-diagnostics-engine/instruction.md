The project at `/app/` contains a Component-Resolved Diagnostics (CRD) engine in TypeScript with several bugs and missing implementations. The allergen knowledge base is at `/app/data/allergens.json`, type definitions at `/app/src/types.ts`, and the main engine at `/app/src/crd-engine.ts`.

Fix the engine so that `cd /app && npm install && echo '<panel_json>' | npx tsx src/cli.ts` reads a `PatientPanel` JSON from stdin and writes a valid `DiagnosticReport` JSON to stdout. The full algorithm specification is at `/app/spec/crd-spec.md`.

**Patient Panel Input:** `{ "patient_id": string, "total_ige_kua_l": number, "results": [{ "allergen_id": string, "sige_kua_l": number }] }`

**DiagnosticReport Output:** Contains `patient_id`, `allergen_results` array, `detected_syndromes` array, and `overall_risk` (highest risk among all results).

Each entry in `allergen_results` must have: `allergen_id`, `allergen_name`, `source`, `cap_class` (0–6), `sige_tige_ratio`, `classification` (`"PRIMARY"` | `"CROSS_REACTIVE"` | `"UNDETERMINED"`), `risk_level` (`"NEGLIGIBLE"` | `"LOW"` | `"MODERATE"` | `"HIGH"` | `"VERY_HIGH"`), `ait_eligible` (boolean).

**CAP Classification:** Uses strict less-than at boundaries 0.10, 0.35, 0.70, 3.50, 17.50, 50.00, 100.00. Values 0.10–<0.35 ("equivocal") are reported as class 0.

**sIgE/tIgE Ratio:** `sIgE / totalIgE`, capped at 1.0. If totalIgE is 0, ratio is 0.

**Cross-Reactivity Resolution:** Positive allergens (class >= 1) are grouped by molecular family. Each is scored: `sIgE * typeWeight * specificityWeight` (see spec for weight tables). Highest score = PRIMARY; others = CROSS_REACTIVE. Allergens without a molecular family or sole in their group: PRIMARY if MAJOR type or class >= 3, else UNDETERMINED. Class 0 results are always UNDETERMINED.

**Risk Levels:** VERY_HIGH: STORAGE_PROTEINS family with class >= 3. HIGH: MAJOR with SEVERE symptom and class >= 2. MODERATE: MAJOR with class >= 2. LOW: all other positives. NEGLIGIBLE: class 0.

**AIT Eligibility:** PRIMARY classification AND MAJOR type AND class >= 2 AND crossReactivityLevel not HIGH.

**Syndrome Detection:** Seven clinical syndromes must be detected per the rules in `/app/spec/crd-spec.md`: Pollen-Food Allergy Syndrome, LTP Syndrome, Pork-Cat Syndrome, Bird-Egg Syndrome, Alpha-Gal Syndrome, Mite-Shrimp Cross-Reactivity, and Latex-Fruit Syndrome. Each uses class >= 1 as the positivity threshold.

Success: the CLI correctly processes arbitrary panels against all specified algorithms.