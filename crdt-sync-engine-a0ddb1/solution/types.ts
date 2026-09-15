
/**
 * Unique identifier for a CRDT item, formed from (clientID, clock) —
 * a Lamport-style timestamp.
 */
export interface ID {
  client: number;
  clock: number;
}

/**
 * A single item in the CRDT struct store.
 * Each map set() operation creates one Item.
 */
export interface Item {
  id: ID;
  /** ID of left neighbor at creation time (null if inserted at start) */
  origin: ID | null;
  /** ID of right neighbor at creation time (null if inserted at end) */
  rightOrigin: ID | null;
  /** Parent type identifier, e.g. "map:inventory" */
  parent: string;
  /** For maps: the key within the map; null for non-map types */
  parentSub: string | null;
  /** The stored value */
  content: any;
  /** Whether this item has been deleted */
  deleted: boolean;
}

/**
 * A contiguous range of deleted clocks for a single client.
 */
export interface DeleteRange {
  clock: number;
  len: number;
}

/**
 * Delete set: maps clientID to sorted array of non-overlapping delete ranges.
 */
export type DeleteSet = Map<number, DeleteRange[]>;

/**
 * State vector: maps clientID to the exclusive upper bound of known clocks.
 * If sv.get(clientID) === 5, clocks 0..4 are known for that client.
 */
export type StateVector = Map<number, number>;

/**
 * Struct store: items indexed by clientID, each array sorted by ascending clock.
 */
export interface StructStore {
  clients: Map<number, Item[]>;
}

/**
 * An update message containing new items and a delete set.
 */
export interface Update {
  structs: Map<number, Item[]>;
  ds: DeleteSet;
}
