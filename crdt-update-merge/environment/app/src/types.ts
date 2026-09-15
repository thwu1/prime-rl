
/**
 * A Lamport timestamp identifying a unique position in the CRDT history.
 */
export interface ID {
  client: number;
  clock: number;
}

/**
 * A single struct (operation) in the CRDT document.
 *
 * Content types:
 *   0 = GC (garbage collected placeholder)
 *   1 = Deleted (tombstone)
 *   2 = String (live content)
 */
export interface Struct {
  id: ID;
  length: number;
  origin: ID | null;
  rightOrigin: ID | null;
  parentKey: string;
  contentType: number;
  contentValue: string | null;
}

/**
 * A range of clock values that have been deleted for a given client.
 * Represents the half-open interval [clock, clock + length).
 */
export interface DeleteRange {
  clock: number;
  length: number;
}

/**
 * A CRDT update message containing structs grouped by client
 * and a delete set of ranges per client.
 */
export interface Update {
  clients: Map<number, Struct[]>;
  deleteSet: Map<number, DeleteRange[]>;
}

export function createUpdate(): Update {
  return { clients: new Map(), deleteSet: new Map() };
}

/**
 * Maps clientID to the next expected clock (one past the highest clock covered).
 */
export type StateVector = Map<number, number>;
