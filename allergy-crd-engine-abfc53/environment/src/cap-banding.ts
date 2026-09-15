
const CAP_LABELS = ['Absent', 'Low', 'Moderate', 'High', 'Very High', 'Ultra High', 'Extremely High'];

export function getCapClass(sIgE: number): number {
  if (sIgE <= 0.35) return 0;
  if (sIgE < 0.70) return 1;
  if (sIgE < 3.50) return 2;
  if (sIgE < 17.50) return 3;
  if (sIgE < 50.00) return 4;
  if (sIgE >= 100.00) return 5;
  return 6;
}

export function getCapLabel(capClass: number): string {
  return CAP_LABELS[capClass] || 'Unknown';
}
