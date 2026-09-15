
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
 * Classify a kUA/L value into CAP class 0-6.
 * All upper boundaries use strict less-than.
 */
export function classifyCapLevel(kua_l: number): number {
  if (kua_l < 0.10) return 0;     // absent/undetectable
  if (kua_l < 0.35) return 0;     // equivocal (0/1 borderline), reported as 0
  if (kua_l < 0.70) return 1;     // low
  if (kua_l < 3.50) return 2;     // moderate
  if (kua_l < 17.50) return 3;    // high
  if (kua_l < 50.00) return 4;    // very high
  if (kua_l < 100.00) return 5;   // ultra high
  return 6;                        // extremely high
}

/**
 * Compute sIgE/tIgE ratio, capped at 1.0.
 */
export function computeSigeTigeRatio(sige: number, totalIge: number): number {
  if (totalIge <= 0) return 0;
  const ratio = sige / totalIge;
  return Math.min(ratio, 1.0);
}

/**
 * Specificity weight: more specific allergens get HIGHER weight.
 * NONE (most specific) = 3.0, HIGH (least specific) = 1.0
 */
function getSpecificityWeight(level: CrossReactivityLevel): number {
  switch (level) {
    case CrossReactivityLevel.NONE: return 3.0;
    case CrossReactivityLevel.LOW: return 2.5;
    case CrossReactivityLevel.MODERATE: return 2.0;
    case CrossReactivityLevel.PROBABLE: return 1.5;
    case CrossReactivityLevel.HIGH: return 1.0;
    default: return 1.0;
  }
}

function getTypeWeight(type: AllergenType): number {
  return type === AllergenType.MAJOR ? 2.0 : 1.0;
}

/**
 * Classify allergens as PRIMARY, CROSS_REACTIVE, or UNDETERMINED.
 */
export function classifyAllergens(
  panelResults: EnrichedResult[]
): Map<string, Classification> {
  const classifications = new Map<string, Classification>();

  // Group positive results by molecular family
  const familyGroups = new Map<string, EnrichedResult[]>();
  const noFamilyResults: EnrichedResult[] = [];

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
    } else {
      noFamilyResults.push(result);
    }
  }

  // Resolve within each family group
  for (const [_family, group] of familyGroups) {
    if (group.length === 1) {
      classifications.set(group[0].allergen.id, Classification.PRIMARY);
      continue;
    }

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

  // Handle allergens without molecular family
  for (const result of noFamilyResults) {
    if (result.allergen.type === AllergenType.MAJOR || result.capClass >= 3) {
      classifications.set(result.allergen.id, Classification.PRIMARY);
    } else {
      classifications.set(result.allergen.id, Classification.UNDETERMINED);
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
  const syndromes: DetectedSyndrome[] = [];
  const positive = panelResults.filter(r => r.capClass >= 1);

  // 1. Pollen-Food Allergy Syndrome
  const pr10Pollen = positive.filter(
    r => r.allergen.molecularFamily === MolecularFamily.PR10
      && r.allergen.category.endsWith('_POLLENS')
  );
  const pr10Food = positive.filter(
    r => r.allergen.molecularFamily === MolecularFamily.PR10
      && r.allergen.category.startsWith('FOOD_')
  );
  if (pr10Pollen.length > 0 && pr10Food.length > 0) {
    const involved = [...pr10Pollen, ...pr10Food].map(r => r.allergen.id);
    syndromes.push({
      name: 'Pollen-Food Allergy Syndrome',
      involved_allergens: involved,
      evidence: `PR-10 cross-reactivity between pollen (${pr10Pollen.map(r => r.allergen.name).join(', ')}) and food (${pr10Food.map(r => r.allergen.name).join(', ')})`
    });
  }

  // 2. LTP Syndrome
  const ltpPositive = positive.filter(
    r => r.allergen.molecularFamily === MolecularFamily.LTP
  );
  const ltpSources = new Set(ltpPositive.map(r => r.allergen.source));
  if (ltpSources.size >= 2) {
    syndromes.push({
      name: 'LTP Syndrome',
      involved_allergens: ltpPositive.map(r => r.allergen.id),
      evidence: `Multiple LTP sensitizations from different sources: ${Array.from(ltpSources).join(', ')}`
    });
  }

  // 3. Pork-Cat Syndrome
  const saCat = positive.filter(
    r => r.allergen.molecularFamily === MolecularFamily.SERUM_ALBUMINS
      && r.allergen.source === 'Cat'
  );
  const saBovine = positive.filter(
    r => r.allergen.molecularFamily === MolecularFamily.SERUM_ALBUMINS
      && r.allergen.source.includes('Cow')
  );
  if (saCat.length > 0 && saBovine.length > 0) {
    const involved = [...saCat, ...saBovine].map(r => r.allergen.id);
    syndromes.push({
      name: 'Pork-Cat Syndrome',
      involved_allergens: involved,
      evidence: 'Serum albumin cross-reactivity between cat and bovine sources'
    });
  }

  // 4. Bird-Egg Syndrome
  const galD5 = positive.find(r => r.allergen.id === 'f75');
  if (galD5) {
    syndromes.push({
      name: 'Bird-Egg Syndrome',
      involved_allergens: ['f75'],
      evidence: 'Gal d 5 (livetin) sensitization indicates bird-egg syndrome'
    });
  }

  // 5. Alpha-Gal Syndrome
  const alphaGal = positive.find(r => r.allergen.id === 'o215');
  if (alphaGal) {
    syndromes.push({
      name: 'Alpha-Gal Syndrome',
      involved_allergens: ['o215'],
      evidence: 'Alpha-Gal carbohydrate sensitization detected'
    });
  }

  // 6. Mite-Shrimp Cross-Reactivity
  const tropoMite = positive.filter(
    r => r.allergen.molecularFamily === MolecularFamily.TROPOMYOSINS
      && r.allergen.category === 'MITES'
  );
  const tropoShellfish = positive.filter(
    r => r.allergen.molecularFamily === MolecularFamily.TROPOMYOSINS
      && r.allergen.category === 'FOOD_SHELLFISH'
  );
  if (tropoMite.length > 0 && tropoShellfish.length > 0) {
    const involved = [...tropoMite, ...tropoShellfish].map(r => r.allergen.id);
    syndromes.push({
      name: 'Mite-Shrimp Cross-Reactivity',
      involved_allergens: involved,
      evidence: 'Tropomyosin cross-reactivity between mites and crustaceans'
    });
  }

  // 7. Latex-Fruit Syndrome
  const latexMarkers = positive.filter(
    r => r.allergen.id === 'k220' || r.allergen.id === 'k224'
  );
  const kiwiAllergens = positive.filter(
    r => r.allergen.source === 'Kiwi'
  );
  if (latexMarkers.length > 0 && kiwiAllergens.length > 0) {
    const involved = [...latexMarkers, ...kiwiAllergens].map(r => r.allergen.id);
    syndromes.push({
      name: 'Latex-Fruit Syndrome',
      involved_allergens: involved,
      evidence: 'Latex allergen sensitization with cross-reactive fruit allergen (kiwi)'
    });
  }

  return syndromes;
}

/**
 * Compute risk level for an allergen result.
 * Evaluated in priority order: NEGLIGIBLE > VERY_HIGH > HIGH > MODERATE > LOW.
 */
export function computeRiskLevel(
  allergen: Allergen,
  capClass: number
): RiskLevel {
  if (capClass === 0) return RiskLevel.NEGLIGIBLE;

  // VERY_HIGH: storage proteins with class >= 3
  if (allergen.molecularFamily === MolecularFamily.STORAGE_PROTEINS && capClass >= 3) {
    return RiskLevel.VERY_HIGH;
  }

  // HIGH: MAJOR with SEVERE symptom and class >= 2
  if (allergen.type === AllergenType.MAJOR
    && allergen.symptoms.includes(SymptomSeverity.SEVERE)
    && capClass >= 2) {
    return RiskLevel.HIGH;
  }

  // MODERATE: MAJOR with class >= 2
  if (allergen.type === AllergenType.MAJOR && capClass >= 2) {
    return RiskLevel.MODERATE;
  }

  return RiskLevel.LOW;
}

/**
 * Determine AIT eligibility.
 * Requires: PRIMARY + MAJOR + class >= 2 + crossReactivityLevel not HIGH
 */
export function computeAitEligibility(
  allergen: Allergen,
  classification: Classification,
  capClass: number
): boolean {
  return classification === Classification.PRIMARY
    && allergen.type === AllergenType.MAJOR
    && capClass >= 2
    && allergen.crossReactivityLevel !== CrossReactivityLevel.HIGH;
}

/**
 * Determine the highest risk level from an array.
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
