
import {
  AllergenComponent, TestResult, RiskAssessment,
  AllergenType, AllergenCategory, SymptomSeverity
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

    if (allergen.symptoms.includes(SymptomSeverity.SEVERE)) {
      anaphylaxisRisk = true;
    }

    if (allergen.symptoms.includes(SymptomSeverity.SEVERE)) {
      hasSevereSymptom = true;
    }

    if (allergen.type === AllergenType.MAJOR && capClass < 2 && aitCategories.has(allergen.category)) {
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
