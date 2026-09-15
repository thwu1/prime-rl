
import { Doc } from './document';
import { StateVector } from './types';
import { encodeStateVector, decodeStateVector, encodeUpdate, decodeUpdate } from './update';

/**
 * Perform a full bidirectional sync between two documents.
 * Uses binary-encoded state vectors and updates.
 *
 * Protocol:
 * 1. A sends state vector to B
 * 2. B computes missing update, encodes, sends to A
 * 3. A decodes and applies
 * 4. B sends state vector to A
 * 5. A computes missing update, encodes, sends to B
 * 6. B decodes and applies
 */
export function syncPair(a: Doc, b: Doc): void {
  // A → B: A's state vector
  const svABytes = encodeStateVector(a.getStateVector());
  const svA = decodeStateVector(svABytes);

  // B computes and sends update for A
  const updateBtoA = b.computeUpdateSince(svA);
  const updateBtoABytes = encodeUpdate(updateBtoA);
  a.applyUpdate(decodeUpdate(updateBtoABytes));

  // B → A: B's state vector
  const svBBytes = encodeStateVector(b.getStateVector());
  const svB = decodeStateVector(svBBytes);

  // A computes and sends update for B
  const updateAtoB = a.computeUpdateSince(svB);
  const updateAtoBBytes = encodeUpdate(updateAtoB);
  b.applyUpdate(decodeUpdate(updateAtoBBytes));
}

/**
 * Compare two state vectors for equality.
 */
function svEqual(a: StateVector, b: StateVector): boolean {
  if (a.size !== b.size) return false;
  for (const [k, v] of a) {
    if (b.get(k) !== v) return false;
  }
  return true;
}

/**
 * Sync all documents pairwise until no more changes occur.
 * After completion, all documents should have identical state.
 */
export function syncAll(docs: Doc[]): void {
  let changed = true;
  let iterations = 0;
  while (changed && iterations < 100) {
    changed = false;
    iterations++;
    for (let i = 0; i < docs.length; i++) {
      for (let j = i + 1; j < docs.length; j++) {
        const svI = new Map(docs[i].getStateVector());
        const svJ = new Map(docs[j].getStateVector());
        syncPair(docs[i], docs[j]);
        if (
          !svEqual(svI, docs[i].getStateVector()) ||
          !svEqual(svJ, docs[j].getStateVector())
        ) {
          changed = true;
        }
      }
    }
  }
}
