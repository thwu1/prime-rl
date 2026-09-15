
import { Update, Struct, DeleteRange, createUpdate } from './types';
import { parseUpdate } from './parse-update';
import { writeUpdate } from './write-update';
import { mergeDeleteSets } from './delete-set';

/**
 * Merge multiple binary-encoded CRDT updates into a single binary update.
 *
 * The merged update contains the union of all structs (deduplicated
 * by clock range per client, sorted by clock) and the union of all
 * delete sets (consolidated into non-overlapping, non-adjacent ranges).
 */
export function mergeUpdates(updates: Uint8Array[]): Uint8Array {
  if (updates.length === 0) {
    return writeUpdate(createUpdate());
  }

  if (updates.length === 1) {
    // Re-encode to normalize client ordering
    return writeUpdate(parseUpdate(updates[0]));
  }

  // Parse all updates
  const parsedUpdates = updates.map(u => parseUpdate(u));

  // Collect all structs per client
  const mergedClients = new Map<number, Struct[]>();
  for (const update of parsedUpdates) {
    for (const [clientID, structs] of update.clients) {
      const existing = mergedClients.get(clientID) || [];
      existing.push(...structs);
      mergedClients.set(clientID, existing);
    }
  }

  // Sort and deduplicate structs per client
  for (const [clientID, structs] of mergedClients) {
    // Sort by clock ascending
    structs.sort((a, b) => a.id.clock - b.id.clock);

    // Deduplicate: skip structs whose clock range is already covered
    const deduped: Struct[] = [];
    let coveredUntil = -1;

    for (const struct of structs) {
      const end = struct.id.clock + struct.length;
      if (struct.id.clock >= coveredUntil) {
        // No overlap with previously accepted structs
        deduped.push(struct);
        coveredUntil = end;
      } else if (end > coveredUntil) {
        // Partial overlap extending beyond covered range
        deduped.push(struct);
        coveredUntil = end;
      }
      // else: fully covered by previous structs, skip
    }

    mergedClients.set(clientID, deduped);
  }

  // Merge all delete sets
  let mergedDeleteSet = new Map<number, DeleteRange[]>();
  for (const update of parsedUpdates) {
    mergedDeleteSet = mergeDeleteSets(mergedDeleteSet, update.deleteSet);
  }

  // Build and serialize result
  const result = createUpdate();
  result.clients = mergedClients;
  result.deleteSet = mergedDeleteSet;

  return writeUpdate(result);
}
