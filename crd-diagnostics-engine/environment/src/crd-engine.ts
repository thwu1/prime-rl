
import * as fs from 'fs';
import * as path from 'path';
import {
  Allergen, PatientPanel, AllergenResult, DiagnosticReport,
  DetectedSyndrome, Classification, RiskLevel, AllergenType,
  CrossReactivityLevel, MolecularFamily, SymptomSeverity
} from './types';

const allergenDataPath = path.resolve(__dirname, '../data/allergens.json');
const allergens: Allergen[] = JSON.parse(fs.readFileSync(allergenDataPath, 'utf-8'));

interface EnrichedResult {
  allergen: Allergen;
  sige: number;
  capClass: number;
}

/**
 * Classify a kUA/L value into CAP class 0-6
 * Scale: 0(<0.10), 0/1(0.10-<0.35 reported as 0), 1(0.35-<0.70),
 * 2(0.70-<3.50), 3(3.50-<17.50), 4(17.50-<50), 5(50-<100), 6(>=100)
 */
export function classifyCapLevel(kua_l: number): number {
  if (kua_l < 0.35) return 0;
  if (kua_l <= 0.70) return 1;
  if (kua_l <= 3.50) return 2;
  if (kua_l <= 17.50) return 3;
  if (kua_l <= 50.00) return 4;
  if (kua_l <= 100.00) return 5;
  return 6;
}

/**
 * Compute sIgE/tIgE ratio
 */
export function computeSigeTigeRatio(sige: number, totalIge: number): number {
  return sige / totalIge;
}

/**
 * Get specificity weight for cross-reactivity scoring.
 * More specific allergens (lower cross-reactivity) should score higher.
 */
function getSpecificityWeight(level: CrossReactivityLevel): number {
  switch (level) {
    case CrossReactivityLevel.NONE: return 1.0;
    case CrossReactivityLevel.LOW: return 1.5;
    case CrossReactivityLevel.MODERATE: return 2.0;
    case CrossReactivityLevel.PROBABLE: return 2.5;
    case CrossReactivityLevel.HIGH: return 3.0;
    default: return 1.0;
  }
}

function getTypeWeight(type: AllergenType): number {
  return type === AllergenType.MAJOR ? 2.0 : 1.0;
}

/**
 * Classify allergens as PRIMARY, CROSS_REACTIVE, or UNDETERMINED
 * based on molecular family grouping and scoring.
 */
export function classifyAllergens(
  panelResults: EnrichedResult[]
): Map<string, Classification> {
  const classifications = new Map<string, Classification>();

  // Group positive results by molecular family
  const familyGroups = new Map<string, EnrichedResult[]>();

  for (const result of panelResults) {
    if (result.capClass === 0) {
      classifications.set(result.allergen.id, Classification.UNDETERMINED);
      continue;
    }

    const family = result.allergen.molecularFamily;
    if (family) {
      const group = familyGroups.get(family) || [];
      group.push(result);
      familyGroups.set(family, group);
    }
    // allergens without molecularFamily are not handled here
  }

  // Resolve within each family group
  for (const [_family, group] of familyGroups) {
    if (group.length === 1) {
      classifications.set(group[0].allergen.id, Classification.PRIMARY);
      continue;
    }

    // Score each allergen in the group
    let bestScore = -1;
    let bestId = '';

    for (const result of group) {
      const score = result.sige
        * getTypeWeight(result.allergen.type)
        * getSpecificityWeight(result.allergen.crossReactivityLevel);

      if (score > bestScore) {
        bestScore = score;
        bestId = result.allergen.id;
      }
    }

    for (const result of group) {
      if (result.allergen.id === bestId) {
        classifications.set(result.allergen.id, Classification.PRIMARY);
      } else {
        classifications.set(result.allergen.id, Classification.CROSS_REACTIVE);
      }
    }
  }

  return classifications;
}

/**
 * Detect clinical syndromes from the panel results.
 */
export function detectSyndromes(
  panelResults: EnrichedResult[]
): DetectedSyndrome[] {
  // TODO: implement syndrome detection
  return [];
}

/**
 * Compute risk level for an allergen result.
 */
export function computeRiskLevel(
  allergen: Allergen,
  capClass: number
): RiskLevel {
  if (capClass === 0) return RiskLevel.NEGLIGIBLE;

  if (allergen.type === AllergenType.MAJOR
    && allergen.symptoms.includes(SymptomSeverity.SEVERE)
    && capClass >= 2) {
    return RiskLevel.HIGH;
  }

  if (allergen.type === AllergenType.MAJOR && capClass >= 2) {
    return RiskLevel.MODERATE;
  }

  return RiskLevel.LOW;
}

/**
 * Determine if an allergen is eligible for allergen immunotherapy (AIT).
 */
export function computeAitEligibility(
  allergen: Allergen,
  classification: Classification,
  capClass: number
): boolean {
  return classification === Classification.PRIMARY
    && allergen.type === AllergenType.MAJOR
    && capClass >= 2;
}

/**
 * Determine the highest risk level from an array of risk levels.
 */
function maxRiskLevel(levels: RiskLevel[]): RiskLevel {
  const order = [
    RiskLevel.NEGLIGIBLE,
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.VERY_HIGH
  ];
  let maxIdx = 0;
  for (const level of levels) {
    const idx = order.indexOf(level);
    if (idx > maxIdx) maxIdx = idx;
  }
  return order[maxIdx];
}

/**
 * Process a patient panel and produce a diagnostic report.
 */
export function processPanel(panel: PatientPanel): DiagnosticReport {
  const panelResults: EnrichedResult[] = panel.results.map(r => {
    const allergen = allergens.find(a => a.id === r.allergen_id);
    if (!allergen) throw new Error(`Unknown allergen: ${r.allergen_id}`);
    return {
      allergen,
      sige: r.sige_kua_l,
      capClass: classifyCapLevel(r.sige_kua_l)
    };
  });

  const classifications = classifyAllergens(panelResults);
  const syndromes = detectSyndromes(panelResults);

  const allergenResults: AllergenResult[] = panelResults.map(r => {
    const classification = classifications.get(r.allergen.id) || Classification.UNDETERMINED;
    const riskLevel = computeRiskLevel(r.allergen, r.capClass);

    return {
      allergen_id: r.allergen.id,
      allergen_name: r.allergen.name,
      source: r.allergen.source,
      cap_class: r.capClass,
      sige_tige_ratio: computeSigeTigeRatio(r.sige, panel.total_ige_kua_l),
      classification,
      risk_level: riskLevel,
      ait_eligible: computeAitEligibility(r.allergen, classification, r.capClass)
    };
  });

  return {
    patient_id: panel.patient_id,
    allergen_results: allergenResults,
    detected_syndromes: syndromes,
    overall_risk: maxRiskLevel(allergenResults.map(r => r.risk_level))
  };
}
