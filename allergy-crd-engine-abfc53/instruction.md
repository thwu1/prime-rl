A Component-Resolved Allergy Diagnostics (CRD) engine at `/app/` processes patient allergen test panels and produces JSON diagnostic reports. The engine fails to compile, contains logic bugs, and its quality-control pipeline is unimplemented. Fix all issues so `cd /app && npm install && npx tsc && node dist/cli.js <input.json>` produces correct output.

**Input**: JSON with `patientId` (string), `totalIgE` (number, kU/L), `results` (array of `{allergenId: string, sIgE: number}`).

**Output** (JSON to stdout): Object with `patientId`, `qualityFlags`, `classifications`, `crossReactivityClusters`, `syndromes`, `riskAssessment`.

**Quality Control** (runs before classification on raw input):
- `DUPLICATE_ENTRY` (warning): same `allergenId` appears multiple times — keep highest sIgE, exclude rest.
- `UNKNOWN_ALLERGEN` (warning): `allergenId` not in allergen database — exclude.
- `NEGATIVE_SIGE` (error): `sIgE < 0` — exclude.
- `CCD_INTERFERENCE` (info): CCD marker `o214` positive (sIgE >= 0.35) — flag only, do not exclude.

Each `qualityFlags` entry: `{code: string, severity: "info"|"warning"|"error", message: string}`. Only validated, deduplicated results feed downstream stages.

Each `classifications` entry: `{allergenId, allergenName, source, sIgE, capClass (0-6), capLabel, sigeToTigeRatio (number = sIgE/totalIgE; 0 if totalIgE is 0), isPrimarySensitization}`.

**CAP Banding** (kUA/L): 0: <0.35 Absent | 1: [0.35,0.70) Low | 2: [0.70,3.50) Moderate | 3: [3.50,17.50) High | 4: [17.50,50.00) Very High | 5: [50.00,100.00) Ultra High | 6: >=100.00 Extremely High.

**Cross-Reactivity Clustering**: Group positive (CAP >= 1) results by `molecularFamily`. Clusters with 2+ members, sorted by sIgE descending; highest member's source = `primarySource`. Sort clusters by family name.

**Primary Sensitization**: Highest sIgE in its molecular family. Allergens without a family are always primary.

**Syndromes** (report all six):
- `pollen-food`: Pollen PR-10 at CAP >= 3 AND food PR-10 at CAP >= 1
- `ltp-syndrome`: >= 2 positive LTP allergens from different sources
- `pork-cat`: Fel d 2 (`e220`) positive AND meat/milk serum albumin positive
- `bird-egg`: Gal d 5 (`f75`) positive
- `alpha-gal`: Alpha-Gal (`o215`) positive
- `latex-fruit`: Latex-category positive AND fruit-category positive

**Risk Assessment**:
- `anaphylaxisRisk`: true if any positive allergen's `pathologies` includes `ANAPHYLAXIS`
- `overallRisk`: `very-high` if maxCAP >= 4 AND anaphylaxisRisk; `high` if maxCAP >= 3 AND SEVERE symptom; `moderate` if maxCAP >= 2; else `low`
- `aitEligible`: true if any MAJOR allergen CAP >= 2 in pollen/mite/mold/venom categories
- `aitRecommendations`: sorted source names of AIT-eligible allergens
