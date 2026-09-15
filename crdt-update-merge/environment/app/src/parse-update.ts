
import { Decoder } from './decoder';
import { Update, Struct, DeleteRange, ID, createUpdate } from './types';

/**
 * Parse a binary-encoded CRDT update into an Update object.
 *
 * Binary format per struct:
 *   flags byte: bit 0 = hasOrigin, bit 1 = hasRightOrigin, bits 2-4 = contentType
 */
export function parseUpdate(data: Uint8Array): Update {
  const decoder = new Decoder(data);
  const update = createUpdate();

  // Read structs grouped by client
  const numClients = decoder.readVarUint();
  for (let i = 0; i < numClients; i++) {
    const clientID = decoder.readVarUint();
    const numStructs = decoder.readVarUint();
    const structs: Struct[] = [];
    let clock = decoder.readVarUint();

    for (let j = 0; j < numStructs; j++) {
      const flags = decoder.readUint8();
      const hasOrigin = (flags & 0x02) !== 0;
      const hasRightOrigin = (flags & 0x01) !== 0;
      const contentType = (flags >> 2) & 0x07;

      const structLength = decoder.readVarUint();

      let origin: ID | null = null;
      if (hasOrigin) {
        origin = { client: decoder.readVarUint(), clock: decoder.readVarUint() };
      }

      let rightOrigin: ID | null = null;
      if (hasRightOrigin) {
        rightOrigin = { client: decoder.readVarUint(), clock: decoder.readVarUint() };
      }

      const parentKey = decoder.readVarString();

      let contentValue: string | null = null;
      if (contentType === 2) {
        contentValue = decoder.readVarString();
      }

      structs.push({
        id: { client: clientID, clock },
        length: structLength,
        origin,
        rightOrigin,
        parentKey,
        contentType,
        contentValue,
      });

      clock += structLength;
    }
    update.clients.set(clientID, structs);
  }

  // Read delete set
  const numDeleteClients = decoder.readVarUint();
  for (let i = 0; i < numDeleteClients; i++) {
    const clientID = decoder.readVarUint();
    const numRanges = decoder.readVarUint();
    const ranges: DeleteRange[] = [];
    for (let j = 0; j < numRanges; j++) {
      ranges.push({
        clock: decoder.readVarUint(),
        length: decoder.readVarUint(),
      });
    }
    update.deleteSet.set(clientID, ranges);
  }

  return update;
}
