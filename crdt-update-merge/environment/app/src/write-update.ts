
import { Encoder } from './encoder';
import { Update } from './types';

/**
 * Serialize an Update object to binary format.
 *
 * Clients must be written in descending order of clientID to ensure
 * consistent conflict resolution during integration.
 */
export function writeUpdate(update: Update): Uint8Array {
  const encoder = new Encoder();

  // Write structs
  const clientIDs = Array.from(update.clients.keys());
  clientIDs.sort((a, b) => a - b);

  encoder.writeVarUint(clientIDs.length);
  for (const clientID of clientIDs) {
    const structs = update.clients.get(clientID)!;
    encoder.writeVarUint(clientID);
    encoder.writeVarUint(structs.length);

    if (structs.length > 0) {
      encoder.writeVarUint(structs[0].id.clock);
    }

    for (const struct of structs) {
      let flags = 0;
      if (struct.origin !== null) flags |= 0x01;
      if (struct.rightOrigin !== null) flags |= 0x02;
      flags |= (struct.contentType & 0x07) << 2;

      encoder.write(flags);
      encoder.writeVarUint(struct.length);

      if (struct.origin !== null) {
        encoder.writeVarUint(struct.origin.client);
        encoder.writeVarUint(struct.origin.clock);
      }
      if (struct.rightOrigin !== null) {
        encoder.writeVarUint(struct.rightOrigin.client);
        encoder.writeVarUint(struct.rightOrigin.clock);
      }

      encoder.writeVarString(struct.parentKey);

      if (struct.contentType === 2) {
        encoder.writeVarString(struct.contentValue || '');
      }
    }
  }

  // Write delete set
  const deleteClientIDs = Array.from(update.deleteSet.keys()).sort((a, b) => a - b);
  encoder.writeVarUint(deleteClientIDs.length);
  for (const clientID of deleteClientIDs) {
    const ranges = update.deleteSet.get(clientID)!;
    encoder.writeVarUint(clientID);
    encoder.writeVarUint(ranges.length);
    for (const range of ranges) {
      encoder.writeVarUint(range.clock);
      encoder.writeVarUint(range.length);
    }
  }

  return encoder.toUint8Array();
}
