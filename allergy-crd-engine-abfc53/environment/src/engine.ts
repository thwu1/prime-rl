
import { PatientPanel, DiagnosticReport, Classification, AllergenComponent } from './types';
import { getCapClass, getCapLabel } from './cap-banding';
import { findCrossReactivityClusters, isPrimarySensitization } from './cross-reactivity';
import { detectSyndromes } from './syndromes';
import { assessRisk } from './risk-assessment';
import { allergenDatabase } from './allergen-db';

export function processPanel(panel: PatientPanel): DiagnosticReport {
  const allergenDb = new Map<string, AllergenComponent>();
  for (const allergen of allergenDatabase) {
    allergenDb.set(allergen.id, allergen);
  }

  const classifications: Classification[] = [];

  for (const result of panel.results) {
    const allergen = allergenDb.get(result.allergenId);
    if (!allergen) continue;

    const capClass = getCapClass(result.sIgE);
    const capLabel = getCapLabel(capClass);
    const ratio = panel.totalIgE > 0 ? result.sIgE / panel.totalIgE : 0;
    const primary = isPrimarySensitization(result.allergenId, panel.results, allergenDb);

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

  const clusters = findCrossReactivityClusters(panel.results, allergenDb);
  const syndromes = detectSyndromes(panel.results, allergenDb);
  const risk = assessRisk(panel.results, allergenDb);

  return {
    patientId: panel.patientId,
    classifications,
    crossReactivityClusters: clusters,
    syndromes,
    riskAssessment: risk
  };
}
