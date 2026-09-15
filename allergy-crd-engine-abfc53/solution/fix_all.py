#!/usr/bin/env python3
"""
Write complete fixed TypeScript source files for the CRD engine.
Fixes: compilation errors, logic bugs, unimplemented QC pipeline, engine integration.

"""


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)
    print(f"Wrote: {path}")


# =============================================================================
# types.ts — Fixes: add GRP enum, sigeToTigeRatio number, qualityFlags field
# =============================================================================
write_file('/app/src/types.ts', """\

export enum AllergenCategory {
  TREE_POLLENS = 'TREE_POLLENS',
  GRASS_POLLENS = 'GRASS_POLLENS',
  WEED_POLLENS = 'WEED_POLLENS',
  ANIMALS = 'ANIMALS',
  MITES = 'MITES',
  MOLDS = 'MOLDS',
  VENOMS = 'VENOMS',
  LATEX = 'LATEX',
  FOOD_PEANUT = 'FOOD_PEANUT',
  FOOD_TREE_NUTS = 'FOOD_TREE_NUTS',
  FOOD_EGG = 'FOOD_EGG',
  FOOD_MILK = 'FOOD_MILK',
  FOOD_FISH = 'FOOD_FISH',
  FOOD_SHELLFISH = 'FOOD_SHELLFISH',
  FOOD_SOY = 'FOOD_SOY',
  FOOD_WHEAT = 'FOOD_WHEAT',
  FOOD_PEACH = 'FOOD_PEACH',
  FOOD_SESAME = 'FOOD_SESAME',
  FOOD_FRUITS_VEGETABLES = 'FOOD_FRUITS_VEGETABLES',
  FOOD_MEAT = 'FOOD_MEAT',
  INSECTS = 'INSECTS',
  PARASITES = 'PARASITES',
  CCD = 'CCD'
}

export enum AllergenType {
  MAJOR = 'MAJOR',
  MINOR = 'MINOR'
}

export enum MolecularFamily {
  PR10 = 'PR10',
  LTP = 'LTP',
  PROFILINS = 'PROFILINS',
  POLCALCINS = 'POLCALCINS',
  TROPOMYOSINS = 'TROPOMYOSINS',
  STORAGE_PROTEINS = 'STORAGE_PROTEINS',
  SERUM_ALBUMINS = 'SERUM_ALBUMINS',
  LIPOCALINS = 'LIPOCALINS',
  PARVALBUMINS = 'PARVALBUMINS',
  GRP = 'GRP'
}

export enum SymptomSeverity {
  ASYMPTOMATIC = 'ASYMPTOMATIC',
  LOCAL = 'LOCAL',
  SYSTEMIC = 'SYSTEMIC',
  SEVERE = 'SEVERE'
}

export enum CrossReactivityLevel {
  NONE = 'NONE',
  LOW = 'LOW',
  MODERATE = 'MODERATE',
  PROBABLE = 'PROBABLE',
  HIGH = 'HIGH'
}

export enum Pathology {
  ALLERGIC_RHINITIS = 'ALLERGIC_RHINITIS',
  ASTHMA = 'ASTHMA',
  SEVERE_ASTHMA = 'SEVERE_ASTHMA',
  FOOD_ALLERGY = 'FOOD_ALLERGY',
  ANAPHYLAXIS = 'ANAPHYLAXIS',
  VENOM_ALLERGY = 'VENOM_ALLERGY',
  OCCUPATIONAL_ALLERGY = 'OCCUPATIONAL_ALLERGY'
}

export interface AllergenComponent {
  id: string;
  name: string;
  source: string;
  extract: string;
  category: AllergenCategory;
  type: AllergenType;
  symptoms: SymptomSeverity[];
  crossReactivity: CrossReactivityLevel;
  crossReactivityDetails: string;
  description: string;
  molecularFamily?: MolecularFamily;
  pathologies?: Pathology[];
}

export interface TestResult {
  allergenId: string;
  sIgE: number;
}

export interface PatientPanel {
  patientId: string;
  totalIgE: number;
  results: TestResult[];
}

export interface QualityFlag {
  code: string;
  severity: 'info' | 'warning' | 'error';
  message: string;
}

export interface Classification {
  allergenId: string;
  allergenName: string;
  source: string;
  sIgE: number;
  capClass: number;
  capLabel: string;
  sigeToTigeRatio: number;
  isPrimarySensitization: boolean;
}

export interface CrossReactivityCluster {
  molecularFamily: string;
  members: { allergenId: string; allergenName: string; sIgE: number }[];
  primarySource: string;
}

export interface SyndromeDetection {
  syndrome: string;
  detected: boolean;
  evidence: string[];
}

export interface RiskAssessment {
  overallRisk: 'low' | 'moderate' | 'high' | 'very-high';
  anaphylaxisRisk: boolean;
  aitEligible: boolean;
  aitRecommendations: string[];
}

export interface DiagnosticReport {
  patientId: string;
  qualityFlags: QualityFlag[];
  classifications: Classification[];
  crossReactivityClusters: CrossReactivityCluster[];
  syndromes: SyndromeDetection[];
  riskAssessment: RiskAssessment;
}
""")


# =============================================================================
# cap-banding.ts — Fixes: boundary < 0.35, swap classes 5/6
# =============================================================================
write_file('/app/src/cap-banding.ts', """\

const CAP_LABELS = ['Absent', 'Low', 'Moderate', 'High', 'Very High', 'Ultra High', 'Extremely High'];

export function getCapClass(sIgE: number): number {
  if (sIgE < 0.35) return 0;
  if (sIgE < 0.70) return 1;
  if (sIgE < 3.50) return 2;
  if (sIgE < 17.50) return 3;
  if (sIgE < 50.00) return 4;
  if (sIgE >= 100.00) return 6;
  return 5;
}

export function getCapLabel(capClass: number): string {
  return CAP_LABELS[capClass] || 'Unknown';
}
""")


# =============================================================================
# cross-reactivity.ts — Fix: group by molecularFamily not category
# =============================================================================
write_file('/app/src/cross-reactivity.ts', """\

import { AllergenComponent, TestResult, CrossReactivityCluster } from './types';
import { getCapClass } from './cap-banding';

export function findCrossReactivityClusters(
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): CrossReactivityCluster[] {
  const groups = new Map<string, { allergenId: string; allergenName: string; source: string; sIgE: number }[]>();

  for (const result of results) {
    if (getCapClass(result.sIgE) === 0) continue;

    const allergen = allergenDb.get(result.allergenId);
    if (!allergen) continue;

    const groupKey = allergen.molecularFamily;
    if (!groupKey) continue;

    if (!groups.has(groupKey)) {
      groups.set(groupKey, []);
    }
    groups.get(groupKey)!.push({
      allergenId: allergen.id,
      allergenName: allergen.name,
      source: allergen.source,
      sIgE: result.sIgE
    });
  }

  const clusters: CrossReactivityCluster[] = [];
  for (const [family, members] of groups) {
    if (members.length < 2) continue;

    members.sort((a, b) => b.sIgE - a.sIgE);

    clusters.push({
      molecularFamily: family,
      members: members.map(m => ({ allergenId: m.allergenId, allergenName: m.allergenName, sIgE: m.sIgE })),
      primarySource: members[0].source
    });
  }

  clusters.sort((a, b) => a.molecularFamily.localeCompare(b.molecularFamily));

  return clusters;
}

export function isPrimarySensitization(
  allergenId: string,
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): boolean {
  const allergen = allergenDb.get(allergenId);
  if (!allergen) return false;

  const result = results.find(r => r.allergenId === allergenId);
  if (!result || getCapClass(result.sIgE) === 0) return false;

  if (!allergen.molecularFamily) return true;

  const familyResults = results
    .filter(r => {
      const a = allergenDb.get(r.allergenId);
      return a && a.molecularFamily === allergen.molecularFamily && getCapClass(r.sIgE) > 0;
    })
    .sort((a, b) => b.sIgE - a.sIgE);

  return familyResults.length > 0 && familyResults[0].allergenId === allergenId;
}
""")


# =============================================================================
# syndromes.ts — Fixes: LTP threshold, pork-cat ID, bird-egg implementation
# =============================================================================

SYNDROMES_TS = """\
import {
  AllergenComponent, TestResult, SyndromeDetection,
  MolecularFamily, AllergenCategory
} from './types';
import { getCapClass } from './cap-banding';

export function detectSyndromes(
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): SyndromeDetection[] {
  return [
    detectPollenFoodSyndrome(results, allergenDb),
    detectLtpSyndrome(results, allergenDb),
    detectPorkCatSyndrome(results, allergenDb),
    detectBirdEggSyndrome(results, allergenDb),
    detectAlphaGalSyndrome(results, allergenDb),
    detectLatexFruitSyndrome(results, allergenDb),
  ];
}

function detectPollenFoodSyndrome(
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): SyndromeDetection {
  const pollenCategories = new Set([
    AllergenCategory.TREE_POLLENS,
    AllergenCategory.GRASS_POLLENS,
    AllergenCategory.WEED_POLLENS
  ]);

  const foodCategories = new Set([
    AllergenCategory.FOOD_PEANUT,
    AllergenCategory.FOOD_TREE_NUTS,
    AllergenCategory.FOOD_SOY,
    AllergenCategory.FOOD_PEACH,
    AllergenCategory.FOOD_FRUITS_VEGETABLES
  ]);

  const pollenPR10s = results.filter(r => {
    const a = allergenDb.get(r.allergenId);
    return a && a.molecularFamily === MolecularFamily.PR10
      && pollenCategories.has(a.category) && getCapClass(r.sIgE) >= 3;
  });

  const foodPR10s = results.filter(r => {
    const a = allergenDb.get(r.allergenId);
    return a && a.molecularFamily === MolecularFamily.PR10
      && foodCategories.has(a.category) && getCapClass(r.sIgE) >= 1;
  });

  const detected = pollenPR10s.length > 0 && foodPR10s.length > 0;
  const evidence: string[] = [];
  if (detected) {
    const pollenNames = pollenPR10s.map(r => allergenDb.get(r.allergenId)!.name);
    const foodNames = foodPR10s.map(r => allergenDb.get(r.allergenId)!.name);
    evidence.push(`Pollen PR-10: ${pollenNames.join(', ')} -> Food PR-10: ${foodNames.join(', ')}`);
  }

  return { syndrome: 'pollen-food', detected, evidence };
}

function detectLtpSyndrome(
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): SyndromeDetection {
  const positiveLTPs = results.filter(r => {
    const a = allergenDb.get(r.allergenId);
    return a && a.molecularFamily === MolecularFamily.LTP && getCapClass(r.sIgE) >= 1;
  });

  const sources = new Set(positiveLTPs.map(r => allergenDb.get(r.allergenId)!.source));

  const detected = sources.size >= 2;

  const evidence: string[] = [];
  if (detected) {
    const names = positiveLTPs.map(r => {
      const a = allergenDb.get(r.allergenId)!;
      return `${a.name} (${a.source})`;
    });
    evidence.push(`LTP positives from ${sources.size} sources: ${names.join(', ')}`);
  }

  return { syndrome: 'ltp-syndrome', detected, evidence };
}

function detectPorkCatSyndrome(
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): SyndromeDetection {
  const catAlbumin = results.find(r => r.allergenId === 'e220' && getCapClass(r.sIgE) >= 1);

  const meatAlbumin = results.find(r => {
    const a = allergenDb.get(r.allergenId);
    return a && a.molecularFamily === MolecularFamily.SERUM_ALBUMINS
      && (a.category === AllergenCategory.FOOD_MILK || a.category === AllergenCategory.FOOD_MEAT)
      && getCapClass(r.sIgE) >= 1;
  });

  const detected = catAlbumin !== undefined && meatAlbumin !== undefined;
  const evidence: string[] = [];
  if (detected) {
    evidence.push('Cat serum albumin positive with meat/milk serum albumin cross-reactivity');
  }

  return { syndrome: 'pork-cat', detected, evidence };
}

function detectBirdEggSyndrome(
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): SyndromeDetection {
  const galD5 = results.find(r => r.allergenId === 'f75' && getCapClass(r.sIgE) >= 1);
  const detected = galD5 !== undefined;
  const evidence: string[] = [];
  if (detected) {
    evidence.push('Gal d 5 (alpha-livetin) positive: ' + galD5!.sIgE + ' kUA/L');
  }
  return { syndrome: 'bird-egg', detected, evidence };
}

function detectAlphaGalSyndrome(
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): SyndromeDetection {
  const alphaGal = results.find(r => r.allergenId === 'o215' && getCapClass(r.sIgE) >= 1);
  const detected = alphaGal !== undefined;
  const evidence: string[] = [];
  if (detected) {
    evidence.push('Alpha-Gal sIgE: ' + alphaGal!.sIgE + ' kUA/L - risk of delayed reactions to red meat');
  }
  return { syndrome: 'alpha-gal', detected, evidence };
}

function detectLatexFruitSyndrome(
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): SyndromeDetection {
  const latexPositive = results.find(r => {
    const a = allergenDb.get(r.allergenId);
    return a && a.category === AllergenCategory.LATEX && getCapClass(r.sIgE) >= 1;
  });

  const fruitCategories = new Set([
    AllergenCategory.FOOD_PEACH,
    AllergenCategory.FOOD_FRUITS_VEGETABLES
  ]);

  const fruitPositive = results.find(r => {
    const a = allergenDb.get(r.allergenId);
    return a && fruitCategories.has(a.category) && getCapClass(r.sIgE) >= 1;
  });

  const detected = latexPositive !== undefined && fruitPositive !== undefined;
  const evidence: string[] = [];
  if (detected) {
    evidence.push('Latex sensitization with fruit cross-reactivity (latex-fruit syndrome)');
  }

  return { syndrome: 'latex-fruit', detected, evidence };
}
"""

write_file('/app/src/syndromes.ts', SYNDROMES_TS)


# =============================================================================
# risk-assessment.ts — Fixes: anaphylaxis from pathology, AIT capClass >= 2
# =============================================================================
write_file('/app/src/risk-assessment.ts', """\

import {
  AllergenComponent, TestResult, RiskAssessment,
  AllergenType, AllergenCategory, SymptomSeverity, Pathology
} from './types';
import { getCapClass } from './cap-banding';

export function assessRisk(
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): RiskAssessment {
  let maxCapClass = 0;
  let anaphylaxisRisk = false;
  let hasSevereSymptom = false;
  const aitSources = new Set<string>();

  const aitCategories = new Set([
    AllergenCategory.TREE_POLLENS,
    AllergenCategory.GRASS_POLLENS,
    AllergenCategory.WEED_POLLENS,
    AllergenCategory.MITES,
    AllergenCategory.MOLDS,
    AllergenCategory.VENOMS
  ]);

  for (const result of results) {
    const capClass = getCapClass(result.sIgE);
    if (capClass === 0) continue;

    const allergen = allergenDb.get(result.allergenId);
    if (!allergen) continue;

    if (capClass > maxCapClass) maxCapClass = capClass;

    if (allergen.pathologies?.includes(Pathology.ANAPHYLAXIS)) {
      anaphylaxisRisk = true;
    }

    if (allergen.symptoms.includes(SymptomSeverity.SEVERE)) {
      hasSevereSymptom = true;
    }

    if (allergen.type === AllergenType.MAJOR && capClass >= 2 && aitCategories.has(allergen.category)) {
      aitSources.add(allergen.source);
    }
  }

  let overallRisk: 'low' | 'moderate' | 'high' | 'very-high';
  if (maxCapClass >= 4 && anaphylaxisRisk) {
    overallRisk = 'very-high';
  } else if (maxCapClass >= 3 && hasSevereSymptom) {
    overallRisk = 'high';
  } else if (maxCapClass >= 2) {
    overallRisk = 'moderate';
  } else {
    overallRisk = 'low';
  }

  return {
    overallRisk,
    anaphylaxisRisk,
    aitEligible: aitSources.size > 0,
    aitRecommendations: Array.from(aitSources).sort()
  };
}
""")


# =============================================================================
# qc.ts — Complete QC pipeline implementation (was unimplemented stub)
# =============================================================================

QC_TS = """\
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
        message: 'Allergen ' + r.allergenId + ': negative sIgE value (' + r.sIgE + ')'
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
        message: 'Allergen ' + r.allergenId + ': not found in database'
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
          message: 'Allergen ' + r.allergenId + ': duplicate removed (sIgE: ' + existing.sIgE + ', kept: ' + r.sIgE + ')'
        });
        bestByAllergen.set(r.allergenId, r);
      } else {
        flags.push({
          code: 'DUPLICATE_ENTRY',
          severity: 'warning',
          message: 'Allergen ' + r.allergenId + ': duplicate removed (sIgE: ' + r.sIgE + ', kept: ' + existing.sIgE + ')'
        });
      }
    } else {
      bestByAllergen.set(r.allergenId, r);
    }
  }
  const deduped = Array.from(bestByAllergen.values());

  // Step 4: CCD interference detection (flag only, no exclusion)
  const ccdResult = deduped.find(r => r.allergenId === 'o214');
  if (ccdResult && getCapClass(ccdResult.sIgE) >= 1) {
    flags.push({
      code: 'CCD_INTERFERENCE',
      severity: 'info',
      message: 'CCD marker o214 positive (sIgE: ' + ccdResult.sIgE + ') - results may include false positives'
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

write_file('/app/src/qc.ts', QC_TS)


# =============================================================================
# engine.ts — Fix: integrate QC, use normalized results, add qualityFlags
# =============================================================================
write_file('/app/src/engine.ts', """\

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
  const validResults = qcResult.normalizedPanel.results;

  const classifications: Classification[] = [];

  for (const result of validResults) {
    const allergen = allergenDb.get(result.allergenId);
    if (!allergen) continue;

    const capClass = getCapClass(result.sIgE);
    const capLabel = getCapLabel(capClass);
    const ratio = panel.totalIgE > 0 ? result.sIgE / panel.totalIgE : 0;
    const primary = isPrimarySensitization(result.allergenId, validResults, allergenDb);

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

  const clusters = findCrossReactivityClusters(validResults, allergenDb);
  const syndromes = detectSyndromes(validResults, allergenDb);
  const risk = assessRisk(validResults, allergenDb);

  return {
    patientId: panel.patientId,
    qualityFlags: qcResult.qualityFlags,
    classifications,
    crossReactivityClusters: clusters,
    syndromes,
    riskAssessment: risk
  };
}
""")


print("\\nAll fixes applied successfully.")
