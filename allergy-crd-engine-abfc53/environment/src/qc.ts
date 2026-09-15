
import { PatientPanel, AllergenComponent, QualityFlag } from './types';

export interface QCResult {
  normalizedPanel: PatientPanel;
  qualityFlags: QualityFlag[];
}

export function runQualityControl(
  panel: PatientPanel,
  allergenDb: Map<string, AllergenComponent>
): QCResult {
  // TODO: validate, deduplicate, detect CCD interference
  throw new Error('Quality control pipeline not yet implemented');
}
