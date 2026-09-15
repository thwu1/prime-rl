
import { DeleteRange } from './types';

/**
 * Merge two sorted delete-range arrays into one consolidated array.
 * Adjacent and overlapping ranges are combined.
 */
export function mergeDeleteRanges(a: DeleteRange[], b: DeleteRange[]): DeleteRange[] {
  const all = [...a, ...b].sort((x, y) => x.clock - y.clock);
  if (all.length === 0) return [];

  const result: DeleteRange[] = [{ ...all[0] }];

  for (let i = 1; i < all.length; i++) {
    const prev = result[result.length - 1];
    const curr = all[i];
    const prevEnd = prev.clock + prev.length;

    if (prevEnd > curr.clock) {
      // Overlapping ranges: extend if necessary
      const currEnd = curr.clock + curr.length;
      if (currEnd > prevEnd) {
        prev.length = currEnd - prev.clock;
      }
    } else {
      result.push({ ...curr });
    }
  }

  return result;
}

/**
 * Merge two delete sets (maps of clientID -> DeleteRange[]).
 */
export function mergeDeleteSets(
  a: Map<number, DeleteRange[]>,
  b: Map<number, DeleteRange[]>
): Map<number, DeleteRange[]> {
  const result = new Map<number, DeleteRange[]>();
  const allClients = new Set([...a.keys(), ...b.keys()]);

  for (const client of allClients) {
    const rangesA = a.get(client) || [];
    const rangesB = b.get(client) || [];
    result.set(client, mergeDeleteRanges(rangesA, rangesB));
  }

  return result;
}
