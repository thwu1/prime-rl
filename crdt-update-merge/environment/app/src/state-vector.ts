
import { Update, StateVector, createUpdate } from './types';
import { Encoder } from './encoder';
import { Decoder } from './decoder';

/**
 * Compute the state vector from an Update.
 * The state vector maps each clientID to the next expected clock.
 */
export function computeStateVector(update: Update): StateVector {
  const sv: StateVector = new Map();
  for (const [clientID, structs] of update.clients) {
    let maxClock = 0;
    for (const struct of structs) {
      const end = struct.id.clock + struct.length - 1;
      if (end > maxClock) {
        maxClock = end;
      }
    }
    sv.set(clientID, maxClock);
  }
  return sv;
}

/**
 * Encode a state vector to binary format.
 * Format: [numEntries: varUint], per entry: [clientID: varUint] [clock: varUint]
 */
export function encodeStateVector(sv: StateVector): Uint8Array {
  const encoder = new Encoder();
  encoder.writeVarUint(sv.size);
  for (const [clientID, clock] of sv) {
    encoder.writeVarUint(clientID);
    encoder.writeVarUint(clock);
  }
  return encoder.toUint8Array();
}

/**
 * Decode a binary state vector.
 */
export function decodeStateVector(data: Uint8Array): StateVector {
  const decoder = new Decoder(data);
  const sv: StateVector = new Map();
  const numEntries = decoder.readVarUint();
  for (let i = 0; i < numEntries; i++) {
    const clientID = decoder.readVarUint();
    const clock = decoder.readVarUint();
    sv.set(clientID, clock);
  }
  return sv;
}

/**
 * Compute the diff between an Update and a remote state vector.
 * Returns a new Update containing only structs missing from the remote.
 * A struct is missing if its clock range extends beyond the remote's known clock.
 */
export function diffUpdate(update: Update, remoteSV: StateVector): Update {
  const result = createUpdate();
  for (const [clientID, structs] of update.clients) {
    const remoteClock = remoteSV.get(clientID) || 0;
    const missing = structs.filter(s => s.id.clock >= remoteClock);
    if (missing.length > 0) {
      result.clients.set(clientID, missing);
    }
  }
  // Delete sets are always included in full
  for (const [clientID, ranges] of update.deleteSet) {
    result.deleteSet.set(clientID, [...ranges]);
  }
  return result;
}
