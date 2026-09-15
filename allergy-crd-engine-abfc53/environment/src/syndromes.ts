
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

  const detected = sources.size < 2;

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
  const catAlbumin = results.find(r => r.allergenId === 'e221' && getCapClass(r.sIgE) >= 1);

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
  return { syndrome: 'bird-egg', detected: false, evidence: [] };
}

function detectAlphaGalSyndrome(
  results: TestResult[],
  allergenDb: Map<string, AllergenComponent>
): SyndromeDetection {
  const alphaGal = results.find(r => r.allergenId === 'o215' && getCapClass(r.sIgE) >= 1);
  const detected = alphaGal !== undefined;
  const evidence: string[] = [];
  if (detected) {
    evidence.push(`Alpha-Gal sIgE: ${alphaGal!.sIgE} kUA/L - risk of delayed reactions to red meat`);
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
