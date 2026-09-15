
import { ID, Item, DeleteRange, DeleteSet, StateVector, StructStore, Update } from './types';

/**
 * Compare two items by (clock, clientID) for LWW conflict resolution.
 * Returns positive if a has higher priority than b.
 */
function compareItemPriority(a: Item, b: Item): number {
  if (a.id.clock !== b.id.clock) return a.id.clock - b.id.clock;
  return a.id.client - b.id.client;
}

export class Doc {
  clientID: number;
  clock: number = 0;
  store: StructStore;

  constructor(clientID: number) {
    this.clientID = clientID;
    this.store = { clients: new Map() };
  }

  /**
   * Add an item to the struct store, maintaining clock-sorted order.
   * Skips if an item with the same (client, clock) already exists.
   */
  private addToStore(item: Item): void {
    let items = this.store.clients.get(item.id.client);
    if (!items) {
      items = [];
      this.store.clients.set(item.id.client, items);
    }
    // Fast path: append if clock is greater than last
    if (items.length === 0 || items[items.length - 1].id.clock < item.id.clock) {
      items.push(item);
      return;
    }
    // Find insertion point
    const idx = items.findIndex(i => i.id.clock >= item.id.clock);
    if (idx >= 0 && items[idx].id.clock === item.id.clock) {
      return; // Already exists
    }
    if (idx < 0) {
      items.push(item);
    } else {
      items.splice(idx, 0, item);
    }
  }

  /**
   * Find an item by its ID using binary search.
   */
  findItem(id: ID): Item | null {
    const items = this.store.clients.get(id.client);
    if (!items) return null;
    let lo = 0, hi = items.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const midClock = items[mid].id.clock;
      if (midClock === id.clock) return items[mid];
      if (midClock < id.clock) lo = mid + 1;
      else hi = mid - 1;
    }
    return null;
  }

  /**
   * Get the current state vector: Map<clientID, exclusive upper bound of clock>.
   */
  getStateVector(): StateVector {
    const sv: StateVector = new Map();
    for (const [clientID, items] of this.store.clients) {
      if (items.length > 0) {
        sv.set(clientID, items[items.length - 1].id.clock + 1);
      }
    }
    return sv;
  }

  /**
   * Set a key in a named map. Creates a new Item in the struct store.
   */
  mapSet(mapName: string, key: string, value: any): void {
    const item: Item = {
      id: { client: this.clientID, clock: this.clock++ },
      origin: null,
      rightOrigin: null,
      parent: `map:${mapName}`,
      parentSub: key,
      content: value,
      deleted: false,
    };
    this.addToStore(item);
  }

  /**
   * Delete a key from a named map by marking the winning item as deleted.
   */
  mapDelete(mapName: string, key: string): void {
    const winner = this.getWinningItem(mapName, key);
    if (winner) {
      winner.deleted = true;
    }
  }

  /**
   * Get the current value of a key in a named map.
   * Returns undefined if the key doesn't exist or is deleted.
   */
  mapGet(mapName: string, key: string): any {
    const winner = this.getWinningItem(mapName, key);
    return winner ? winner.content : undefined;
  }

  /**
   * Get all key-value pairs in a named map (only non-deleted winners).
   */
  mapEntries(mapName: string): Map<string, any> {
    const parent = `map:${mapName}`;
    const entries = new Map<string, any>();
    const keys = new Set<string>();
    for (const [, items] of this.store.clients) {
      for (const item of items) {
        if (item.parent === parent && item.parentSub !== null) {
          keys.add(item.parentSub);
        }
      }
    }
    for (const key of keys) {
      const winner = this.getWinningItem(mapName, key);
      if (winner) {
        entries.set(key, winner.content);
      }
    }
    return entries;
  }

  /**
   * Find the winning (non-deleted, highest priority) item for a map key.
   * Priority: lexicographically greatest (clock, clientID).
   */
  private getWinningItem(mapName: string, key: string): Item | null {
    const parent = `map:${mapName}`;
    let winner: Item | null = null;
    for (const [, items] of this.store.clients) {
      for (const item of items) {
        if (item.parent === parent && item.parentSub === key && !item.deleted) {
          if (!winner || compareItemPriority(item, winner) > 0) {
            winner = item;
          }
        }
      }
    }
    return winner;
  }

  /**
   * Apply a remote update: integrate all new items, then apply delete set.
   */
  applyUpdate(update: Update): void {
    // Integrate new items
    for (const [, items] of update.structs) {
      for (const item of items) {
        if (!this.findItem(item.id)) {
          this.addToStore({
            id: { client: item.id.client, clock: item.id.clock },
            origin: item.origin
              ? { client: item.origin.client, clock: item.origin.clock }
              : null,
            rightOrigin: item.rightOrigin
              ? { client: item.rightOrigin.client, clock: item.rightOrigin.clock }
              : null,
            parent: item.parent,
            parentSub: item.parentSub,
            content: item.content,
            deleted: item.deleted,
          });
        }
      }
    }
    // Apply delete set
    for (const [clientID, ranges] of update.ds) {
      for (const range of ranges) {
        for (let clock = range.clock; clock < range.clock + range.len; clock++) {
          const item = this.findItem({ client: clientID, clock });
          if (item) {
            item.deleted = true;
          }
        }
      }
    }
  }

  /**
   * Compute an update containing items the remote peer is missing,
   * plus delete set entries for items the remote has but are locally deleted.
   */
  computeUpdateSince(remoteSV: StateVector): Update {
    const structs: Map<number, Item[]> = new Map();
    const ds: DeleteSet = new Map();

    for (const [clientID, items] of this.store.clients) {
      const remoteClock = remoteSV.get(clientID) || 0;

      // Items the remote doesn't have yet
      const missing = items.filter(item => item.id.clock >= remoteClock);
      if (missing.length > 0) {
        structs.set(clientID, missing);
      }

      // Delete set: items the remote already has but are locally deleted
      const deletedInKnown: DeleteRange[] = [];
      for (const item of items) {
        if (item.deleted && item.id.clock < remoteClock) {
          deletedInKnown.push({ clock: item.id.clock, len: 1 });
        }
      }
      if (deletedInKnown.length > 0) {
        // Sort and merge adjacent ranges
        deletedInKnown.sort((a, b) => a.clock - b.clock);
        const merged: DeleteRange[] = [];
        for (const range of deletedInKnown) {
          if (
            merged.length > 0 &&
            merged[merged.length - 1].clock + merged[merged.length - 1].len === range.clock
          ) {
            merged[merged.length - 1].len += range.len;
          } else {
            merged.push({ clock: range.clock, len: range.len });
          }
        }
        ds.set(clientID, merged);
      }
    }

    return { structs, ds };
  }
}
