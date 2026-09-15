
import { ID, Item, Update, StateVector, DeleteSet, DeleteRange } from './types';
import { Encoder, Decoder } from './encoding';

/**
 * Encode a state vector to binary.
 * Format: varUint(numEntries), per entry: varUint(clientID), varUint(clock).
 * Entries sorted ascending by clientID.
 */
export function encodeStateVector(sv: StateVector): Uint8Array {
  const encoder = new Encoder();
  const sorted = [...sv.entries()].sort((a, b) => a[0] - b[0]);
  encoder.writeVarUint(sorted.length);
  for (const [clientID, clock] of sorted) {
    encoder.writeVarUint(clientID);
    encoder.writeVarUint(clock);
  }
  return encoder.toUint8Array();
}

/**
 * Decode a state vector from binary.
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
 * Encode an Update to binary.
 *
 * Structs section:
 *   varUint(numGroups)
 *   per group (sorted by clientID ascending):
 *     varUint(clientID), varUint(numItems), varUint(firstClock)
 *     per item:
 *       byte(info): bit0=hasParentSub, bit1=deleted, bit2=hasOrigin, bit3=hasRightOrigin
 *       varString(parent)
 *       [varString(parentSub)] if hasParentSub
 *       [varUint(originClient), varUint(originClock)] if hasOrigin
 *       [varUint(rightOriginClient), varUint(rightOriginClock)] if hasRightOrigin
 *       [writeAny(content)] if !deleted
 *
 * Delete set section:
 *   varUint(numClients)
 *   per client (sorted by clientID ascending):
 *     varUint(clientID), varUint(numRanges)
 *     per range (sorted by clock ascending):
 *       varUint(clock), varUint(len)
 */
export function encodeUpdate(update: Update): Uint8Array {
  const encoder = new Encoder();

  // Structs
  const sortedClients = [...update.structs.entries()].sort((a, b) => a[0] - b[0]);
  encoder.writeVarUint(sortedClients.length);

  for (const [clientID, items] of sortedClients) {
    encoder.writeVarUint(clientID);
    encoder.writeVarUint(items.length);
    if (items.length > 0) {
      encoder.writeVarUint(items[0].id.clock);
    }

    for (const item of items) {
      let info = 0;
      if (item.parentSub !== null) info |= 1;
      if (item.deleted) info |= 2;
      if (item.origin !== null) info |= 4;
      if (item.rightOrigin !== null) info |= 8;
      encoder.writeByte(info);

      encoder.writeVarString(item.parent);
      if (item.parentSub !== null) {
        encoder.writeVarString(item.parentSub);
      }
      if (item.origin !== null) {
        encoder.writeVarUint(item.origin.client);
        encoder.writeVarUint(item.origin.clock);
      }
      if (item.rightOrigin !== null) {
        encoder.writeVarUint(item.rightOrigin.client);
        encoder.writeVarUint(item.rightOrigin.clock);
      }
      if (!item.deleted) {
        encoder.writeAny(item.content);
      }
    }
  }

  // Delete set
  const sortedDS = [...update.ds.entries()].sort((a, b) => a[0] - b[0]);
  encoder.writeVarUint(sortedDS.length);
  for (const [clientID, ranges] of sortedDS) {
    encoder.writeVarUint(clientID);
    const sortedRanges = [...ranges].sort((a, b) => a.clock - b.clock);
    encoder.writeVarUint(sortedRanges.length);
    for (const range of sortedRanges) {
      encoder.writeVarUint(range.clock);
      encoder.writeVarUint(range.len);
    }
  }

  return encoder.toUint8Array();
}

/**
 * Decode an Update from binary.
 */
export function decodeUpdate(data: Uint8Array): Update {
  const decoder = new Decoder(data);
  const structs: Map<number, Item[]> = new Map();

  const numGroups = decoder.readVarUint();
  for (let g = 0; g < numGroups; g++) {
    const clientID = decoder.readVarUint();
    const numItems = decoder.readVarUint();
    let clock = numItems > 0 ? decoder.readVarUint() : 0;
    const items: Item[] = [];

    for (let i = 0; i < numItems; i++) {
      const info = decoder.readByte();
      const hasParentSub = (info & 1) !== 0;
      const deleted = (info & 2) !== 0;
      const hasOrigin = (info & 4) !== 0;
      const hasRightOrigin = (info & 8) !== 0;

      const parent = decoder.readVarString();
      const parentSub = hasParentSub ? decoder.readVarString() : null;

      let origin: ID | null = null;
      if (hasOrigin) {
        origin = { client: decoder.readVarUint(), clock: decoder.readVarUint() };
      }
      let rightOrigin: ID | null = null;
      if (hasRightOrigin) {
        rightOrigin = { client: decoder.readVarUint(), clock: decoder.readVarUint() };
      }

      let content: any = undefined;
      if (!deleted) {
        content = decoder.readAny();
      }

      items.push({
        id: { client: clientID, clock },
        origin,
        rightOrigin,
        parent,
        parentSub,
        content,
        deleted,
      });
      clock++;
    }

    structs.set(clientID, items);
  }

  // Delete set
  const ds: DeleteSet = new Map();
  const numDSClients = decoder.readVarUint();
  for (let i = 0; i < numDSClients; i++) {
    const clientID = decoder.readVarUint();
    const numRanges = decoder.readVarUint();
    const ranges: DeleteRange[] = [];
    for (let j = 0; j < numRanges; j++) {
      ranges.push({
        clock: decoder.readVarUint(),
        len: decoder.readVarUint(),
      });
    }
    ds.set(clientID, ranges);
  }

  return { structs, ds };
}

/**
 * Merge multiple binary-encoded updates into a single update.
 * Deduplicates items by (clientID, clock) and merges delete set ranges.
 * The result, when applied to an empty doc, yields the same state
 * as applying all input updates sequentially.
 */
export function mergeUpdates(updates: Uint8Array[]): Uint8Array {
  // Collect all items, deduplicating by (client, clock)
  const allStructs: Map<number, Map<number, Item>> = new Map();
  const allDS: Map<number, DeleteRange[]> = new Map();

  for (const updateBytes of updates) {
    const update = decodeUpdate(updateBytes);

    for (const [clientID, items] of update.structs) {
      if (!allStructs.has(clientID)) {
        allStructs.set(clientID, new Map());
      }
      const clientItems = allStructs.get(clientID)!;
      for (const item of items) {
        if (!clientItems.has(item.id.clock)) {
          clientItems.set(item.id.clock, item);
        }
      }
    }

    for (const [clientID, ranges] of update.ds) {
      if (!allDS.has(clientID)) {
        allDS.set(clientID, []);
      }
      allDS.get(clientID)!.push(...ranges);
    }
  }

  // Convert to Update format
  const structs: Map<number, Item[]> = new Map();
  for (const [clientID, clockMap] of allStructs) {
    const items = [...clockMap.values()].sort((a, b) => a.id.clock - b.id.clock);
    structs.set(clientID, items);
  }

  // Merge overlapping delete set ranges
  const ds: DeleteSet = new Map();
  for (const [clientID, ranges] of allDS) {
    ranges.sort((a, b) => a.clock - b.clock);
    const merged: DeleteRange[] = [];
    for (const range of ranges) {
      if (
        merged.length > 0 &&
        merged[merged.length - 1].clock + merged[merged.length - 1].len >= range.clock
      ) {
        const last = merged[merged.length - 1];
        last.len = Math.max(last.len, range.clock + range.len - last.clock);
      } else {
        merged.push({ clock: range.clock, len: range.len });
      }
    }
    ds.set(clientID, merged);
  }

  return encodeUpdate({ structs, ds });
}
