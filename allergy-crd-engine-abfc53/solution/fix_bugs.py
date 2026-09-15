#!/usr/bin/env python3
"""
Fix all bugs in the CRD engine and implement the QC pipeline.

"""

import os


def fix_file(path: str, replacements: list[tuple[str, str]]):
    with open(path, 'r') as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Could not find target string in {path}:\n{old!r}")
        content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"Fixed: {path} ({len(replacements)} replacement(s))")


def write_file(path: str, content: str):
    with open(path, 'w') as f:
        f.write(content)
    print(f"Wrote: {path}")


# === Fix 1: types.ts — Add missing GRP enum member ===
# === Fix 2: types.ts — Change sigeToTigeRatio from string to number ===
# === Fix 3: types.ts — Add qualityFlags to DiagnosticReport ===
fix_file('/app/src/types.ts', [
    (
        "  PARVALBUMINS = 'PARVALBUMINS'\n}",
        "  PARVALBUMINS = 'PARVALBUMINS',\n  GRP = 'GRP'\n}"
    ),
    (
        "  sigeToTigeRatio: string;",
        "  sigeToTigeRatio: number;"
    ),
    (
        "  patientId: string;\n  classifications:",
        "  patientId: string;\n  qualityFlags: QualityFlag[];\n  classifications:"
    ),
])


# === Fix 4 & 5: cap-banding.ts — Fix boundary at 0.35 and swap classes 5/6 ===
fix_file('/app/src/cap-banding.ts', [
    (
        "  if (sIgE <= 0.35) return 0;",
        "  if (sIgE < 0.35) return 0;"
    ),
    (
        "  if (sIgE >= 100.00) return 5;\n  return 6;",
        "  if (sIgE >= 100.00) return 6;\n  return 5;"
    ),
])


# === Fix 6: cross-reactivity.ts — Group by molecularFamily, not category ===
fix_file('/app/src/cross-reactivity.ts', [
    (
        "    const groupKey = allergen.category;",
        "    const groupKey = allergen.molecularFamily;"
    ),
])


# === Fix 7: syndromes.ts — Fix LTP threshold (< 2 → >= 2) ===
# === Fix 8: syndromes.ts — Fix pork-cat allergen ID (e221 → e220) ===
# === Fix 9: syndromes.ts — Implement bird-egg syndrome ===
fix_file('/app/src/syndromes.ts', [
    (
        "  const detected = sources.size < 2;",
        "  const detected = sources.size >= 2;"
    ),
    (
        "  const catAlbumin = results.find(r => r.allergenId === 'e221' && getCapClass(r.sIgE) >= 1);",
        "  const catAlbumin = results.find(r => r.allergenId === 'e220' && getCapClass(r.sIgE) >= 1);"
    ),
    (
        "  return { syndrome: 'bird-egg', detected: false, evidence: [] };",
        """  const galD5 = results.find(r => r.allergenId === 'f75' && getCapClass(r.sIgE) >= 1);
  const detected = galD5 !== undefined;
  const evidence: string[] = [];
  if (detected) {
    evidence.push(`Gal d 5 (alpha-livetin) positive: ${galD5!.sIgE} kUA/L`);
  }
  return { syndrome: 'bird-egg', detected, evidence };"""
    ),
])


# === Fix 10: risk-assessment.ts — Check ANAPHYLAXIS pathology instead of SEVERE symptom ===
# === Fix 11: risk-assessment.ts — Fix AIT condition (< 2 → >= 2) ===
fix_file('/app/src/risk-assessment.ts', [
    (
        "  AllergenType, AllergenCategory, SymptomSeverity\n} from './types';",
        "  AllergenType, AllergenCategory, SymptomSeverity, Pathology\n} from './types';"
    ),
    (
        "    if (allergen.symptoms.includes(SymptomSeverity.SEVERE)) {\n      anaphylaxisRisk = true;\n    }\n\n    if (allergen.symptoms.includes(SymptomSeverity.SEVERE)) {\n      hasSevereSymptom = true;\n    }",
        "    if (allergen.pathologies?.includes(Pathology.ANAPHYLAXIS)) {\n      anaphylaxisRisk = true;\n    }\n\n    if (allergen.symptoms.includes(SymptomSeverity.SEVERE)) {\n      hasSevereSymptom = true;\n    }"
    ),
    (
        "    if (allergen.type === AllergenType.MAJOR && capClass < 2 && aitCategories.has(allergen.category)) {",
        "    if (allergen.type === AllergenType.MAJOR && capClass >= 2 && aitCategories.has(allergen.category)) {"
    ),
])


# === Fix 12: Implement the QC pipeline (was a stub that throws) ===
QC_CONTENT = '''\

import { PatientPanel, AllergenComponent, QualityFlag } from './types';
import { getCapClass } from './cap-banding';

export interface QCResult {
  normalizedPanel: PatientPanel;
  qualityFlags: QualityFlag[];
}

export function runQualityControl(
  panel: PatientPanel,
  allergenDb: Map<string, AllergenComponent>
): QCResult {
  const flags: QualityFlag[] = [];

  // Step 1: Exclude negative sIgE values
  const nonNegative = panel.results.filter(r => {
    if (r.sIgE < 0) {
      flags.push({
        code: 'NEGATIVE_SIGE',
        severity: 'error',
        message: `Allergen ${r.allergenId}: negative sIgE value (${r.sIgE})`
      });
      return false;
    }
    return true;
  });

  // Step 2: Exclude unknown allergens
  const known = nonNegative.filter(r => {
    if (!allergenDb.has(r.allergenId)) {
      flags.push({
        code: 'UNKNOWN_ALLERGEN',
        severity: 'warning',
        message: `Allergen ${r.allergenId}: not found in database`
      });
      return false;
    }
    return true;
  });

  // Step 3: Deduplicate — keep highest sIgE per allergenId
  const bestByAllergen = new Map<string, { allergenId: string; sIgE: number }>();
  for (const r of known) {
    const existing = bestByAllergen.get(r.allergenId);
    if (existing) {
      if (r.sIgE > existing.sIgE) {
        flags.push({
          code: 'DUPLICATE_ENTRY',
          severity: 'warning',
          message: `Allergen ${r.allergenId}: duplicate removed (sIgE: ${existing.sIgE}, kept: ${r.sIgE})`
        });
        bestByAllergen.set(r.allergenId, r);
      } else {
        flags.push({
          code: 'DUPLICATE_ENTRY',
          severity: 'warning',
          message: `Allergen ${r.allergenId}: duplicate removed (sIgE: ${r.sIgE}, kept: ${existing.sIgE})`
        });
      }
    } else {
      bestByAllergen.set(r.allergenId, r);
    }
  }
  const deduped = Array.from(bestByAllergen.values());

  // Step 4: CCD interference detection
  const ccdResult = deduped.find(r => r.allergenId === 'o214');
  if (ccdResult && getCapClass(ccdResult.sIgE) >= 1) {
    flags.push({
      code: 'CCD_INTERFERENCE',
      severity: 'info',
      message: `CCD marker o214 positive (sIgE: ${ccdResult.sIgE}) — results may include false positives`
    });
  }

  return {
    normalizedPanel: {
      ...panel,
      results: deduped
    },
    qualityFlags: flags
  };
}
'''

write_file('/app/src/qc.ts', QC_CONTENT)


# === Fix 13: engine.ts — Use normalized results + add qualityFlags to output ===
fix_file('/app/src/engine.ts', [
    # Use normalized results in the for loop
    (
        "  for (const result of panel.results) {",
        "  for (const result of qcResult.normalizedPanel.results) {"
    ),
    # Fix isPrimarySensitization to use normalized results
    (
        "isPrimarySensitization(result.allergenId, panel.results, allergenDb)",
        "isPrimarySensitization(result.allergenId, qcResult.normalizedPanel.results, allergenDb)"
    ),
    # Fix downstream calls to use normalized results
    (
        "findCrossReactivityClusters(panel.results, allergenDb)",
        "findCrossReactivityClusters(qcResult.normalizedPanel.results, allergenDb)"
    ),
    (
        "detectSyndromes(panel.results, allergenDb)",
        "detectSyndromes(qcResult.normalizedPanel.results, allergenDb)"
    ),
    (
        "assessRisk(panel.results, allergenDb)",
        "assessRisk(qcResult.normalizedPanel.results, allergenDb)"
    ),
    # Add qualityFlags to the return object
    (
        "    patientId: panel.patientId,\n    classifications,",
        "    patientId: panel.patientId,\n    qualityFlags: qcResult.qualityFlags,\n    classifications,"
    ),
])


print("\nAll fixes applied successfully.")
