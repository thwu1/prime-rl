#!/usr/bin/env python3
"""
Fix all bugs in the CRD engine and implement the QC pipeline.

"""

import sys


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)
    print(f"Wrote: {path}")


def fix_line(content, pattern, old, new):
    """Find the first line containing `pattern` and replace `old` with `new` in that line."""
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if pattern in line and old in line:
            lines[i] = line.replace(old, new, 1)
            return '\n'.join(lines)
    raise ValueError(f"fix_line failed: pattern={pattern!r}, old={old!r}")


def insert_after(content, pattern, insertion):
    """Insert a new line after the first line containing `pattern`."""
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if pattern in line:
            lines.insert(i + 1, insertion)
            return '\n'.join(lines)
    raise ValueError(f"insert_after failed: pattern={pattern!r}")


# ============================================================
# Fix 1: types.ts — Add GRP enum, fix ratio type, add qualityFlags
# ============================================================
content = read_file('/app/src/types.ts')

# 1a. Add GRP to MolecularFamily enum (add comma + new member)
content = fix_line(content,
    "PARVALBUMINS = 'PARVALBUMINS'",
    "PARVALBUMINS = 'PARVALBUMINS'",
    "PARVALBUMINS = 'PARVALBUMINS',")
content = insert_after(content,
    "PARVALBUMINS = 'PARVALBUMINS',",
    "  GRP = 'GRP'")

# 1b. Fix sigeToTigeRatio type from string to number
content = fix_line(content,
    "sigeToTigeRatio",
    "sigeToTigeRatio: string;",
    "sigeToTigeRatio: number;")

# 1c. Add qualityFlags field to DiagnosticReport interface
# Must insert after the patientId line that is INSIDE DiagnosticReport
lines = content.split('\n')
in_diagnostic = False
for i, line in enumerate(lines):
    if 'export interface DiagnosticReport' in line:
        in_diagnostic = True
    if in_diagnostic and 'patientId: string;' in line:
        lines.insert(i + 1, '  qualityFlags: QualityFlag[];')
        break
content = '\n'.join(lines)

write_file('/app/src/types.ts', content)
print("  -> Added GRP enum member, fixed sigeToTigeRatio type, added qualityFlags field")


# ============================================================
# Fix 2: cap-banding.ts — Fix boundary and swap classes 5/6
# ============================================================
content = read_file('/app/src/cap-banding.ts')

# 2a. Fix boundary at 0.35: inclusive (<=) → exclusive (<)
content = fix_line(content,
    "0.35",
    "sIgE <= 0.35",
    "sIgE < 0.35")

# 2b. Swap class 5 and 6: the >= 100 line returns 5 (wrong), should return 6
content = fix_line(content,
    "sIgE >= 100.00",
    "return 5;",
    "return 6;")

# 2c. The default return was 6 (wrong), should be 5
# Find the last bare "return 6;" (not in an if-statement)
lines = content.split('\n')
for i in range(len(lines) - 1, -1, -1):
    if 'return 6;' in lines[i] and 'if' not in lines[i]:
        lines[i] = lines[i].replace('return 6;', 'return 5;')
        break
content = '\n'.join(lines)

write_file('/app/src/cap-banding.ts', content)
print("  -> Fixed 0.35 boundary, swapped classes 5/6")


# ============================================================
# Fix 3: cross-reactivity.ts — Group by molecularFamily, not category
# ============================================================
content = read_file('/app/src/cross-reactivity.ts')

content = fix_line(content,
    "groupKey",
    "allergen.category",
    "allergen.molecularFamily")

write_file('/app/src/cross-reactivity.ts', content)
print("  -> Changed grouping from category to molecularFamily")


# ============================================================
# Fix 4: syndromes.ts — Fix LTP threshold, pork-cat ID, bird-egg
# ============================================================
content = read_file('/app/src/syndromes.ts')

# 4a. Fix LTP syndrome threshold: < 2 → >= 2
content = fix_line(content,
    "sources.size",
    "sources.size < 2",
    "sources.size >= 2")

# 4b. Fix pork-cat allergen ID: e221 (dog albumin) → e220 (cat albumin)
content = fix_line(content,
    "e221",
    "e221",
    "e220")

# 4c. Implement bird-egg syndrome detection (was hardcoded false)
content = content.replace(
    "  return { syndrome: 'bird-egg', detected: false, evidence: [] };",
    """  const galD5 = results.find(r => r.allergenId === 'f75' && getCapClass(r.sIgE) >= 1);
  const detected = galD5 !== undefined;
  const evidence: string[] = [];
  if (detected) {
    evidence.push(`Gal d 5 (alpha-livetin) positive: ${galD5!.sIgE} kUA/L`);
  }
  return { syndrome: 'bird-egg', detected, evidence };""")

write_file('/app/src/syndromes.ts', content)
print("  -> Fixed LTP threshold, pork-cat ID, implemented bird-egg")


# ============================================================
# Fix 5: risk-assessment.ts — Fix anaphylaxis check and AIT condition
# ============================================================
content = read_file('/app/src/risk-assessment.ts')

# 5a. Add Pathology to imports
content = fix_line(content,
    "AllergenType, AllergenCategory, SymptomSeverity",
    "SymptomSeverity",
    "SymptomSeverity, Pathology")

# 5b. Fix anaphylaxis check: use Pathology.ANAPHYLAXIS instead of SymptomSeverity.SEVERE
# Only replace the FIRST occurrence (the anaphylaxis one, not the hasSevereSymptom one)
old_check = "allergen.symptoms.includes(SymptomSeverity.SEVERE)"
new_check = "allergen.pathologies?.includes(Pathology.ANAPHYLAXIS)"
idx = content.index(old_check)
content = content[:idx] + new_check + content[idx + len(old_check):]

# 5c. Fix AIT eligibility condition: < 2 → >= 2
content = fix_line(content,
    "capClass",
    "capClass < 2",
    "capClass >= 2")

write_file('/app/src/risk-assessment.ts', content)
print("  -> Fixed anaphylaxis check, AIT condition")


# ============================================================
# Fix 6: qc.ts — Complete quality control implementation
# ============================================================
qc_content = """\

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
"""

write_file('/app/src/qc.ts', qc_content)
print("  -> Complete QC pipeline implementation")


# ============================================================
# Fix 7: engine.ts — Complete rewrite with QC integration
# ============================================================
engine_content = """\

import { PatientPanel, DiagnosticReport, Classification, AllergenComponent } from './types';
import { getCapClass, getCapLabel } from './cap-banding';
import { findCrossReactivityClusters, isPrimarySensitization } from './cross-reactivity';
import { detectSyndromes } from './syndromes';
import { assessRisk } from './risk-assessment';
import { allergenDatabase } from './allergen-db';
import { runQualityControl } from './qc';

export function processPanel(panel: PatientPanel): DiagnosticReport {
  const allergenDb = new Map<string, AllergenComponent>();
  for (const allergen of allergenDatabase) {
    allergenDb.set(allergen.id, allergen);
  }

  const qcResult = runQualityControl(panel, allergenDb);

  const classifications: Classification[] = [];

  for (const result of qcResult.normalizedPanel.results) {
    const allergen = allergenDb.get(result.allergenId);
    if (!allergen) continue;

    const capClass = getCapClass(result.sIgE);
    const capLabel = getCapLabel(capClass);
    const ratio = panel.totalIgE > 0 ? result.sIgE / panel.totalIgE : 0;
    const primary = isPrimarySensitization(result.allergenId, qcResult.normalizedPanel.results, allergenDb);

    classifications.push({
      allergenId: allergen.id,
      allergenName: allergen.name,
      source: allergen.source,
      sIgE: result.sIgE,
      capClass,
      capLabel,
      sigeToTigeRatio: ratio,
      isPrimarySensitization: primary
    });
  }

  const clusters = findCrossReactivityClusters(qcResult.normalizedPanel.results, allergenDb);
  const syndromes = detectSyndromes(qcResult.normalizedPanel.results, allergenDb);
  const risk = assessRisk(qcResult.normalizedPanel.results, allergenDb);

  return {
    patientId: panel.patientId,
    qualityFlags: qcResult.qualityFlags,
    classifications,
    crossReactivityClusters: clusters,
    syndromes,
    riskAssessment: risk
  };
}
"""

write_file('/app/src/engine.ts', engine_content)
print("  -> Complete engine rewrite with QC integration")


print("\nAll fixes applied successfully.")
