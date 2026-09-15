
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

    const groupKey = allergen.category;
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
