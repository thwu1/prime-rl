package compaction;

import java.util.*;


/**
 * Merges multiple SSTables into a single compacted result.
 *
 * Merge rules:
 * - For each key, the entry with the highest timestamp wins
 * - Expired TTL entries become implicit tombstones at timestamp+ttl
 * - Tombstones purgeable when gc_grace elapsed AND all overlapping SSTables included
 * - Non-purgeable tombstones must be retained in output
 */
public class MergeEngine {

    public static List<Entry> merge(List<List<Entry>> sstableEntries,
                                     List<SSTable> mergedSSTables,
                                     List<SSTable> allSSTables,
                                     long currentTime,
                                     long gcGraceSeconds) {

        // Step 1: For each key, pick the winning entry.
        // Convert expired TTL entries to implicit tombstones first.
        Map<String, Entry> winners = new TreeMap<>();

        for (List<Entry> entries : sstableEntries) {
            for (Entry e : entries) {
                // Convert expired TTL to implicit tombstone
                Entry effective = e;
                if (e.type == 'T' && e.timestamp + e.ttl <= currentTime) {
                    effective = new Entry(e.key, e.timestamp + e.ttl,
                                          'D', null, 0);
                }

                Entry existing = winners.get(effective.key);
                if (existing == null) {
                    winners.put(effective.key, effective);
                } else {
                    // Highest timestamp wins
                    if (effective.timestamp > existing.timestamp) {
                        winners.put(effective.key, effective);
                    } else if (effective.timestamp == existing.timestamp
                               && effective.type == 'D'
                               && existing.type != 'D') {
                        // Tie-break: DELETE wins over VALUE/TTL
                        winners.put(effective.key, effective);
                    }
                }
            }
        }

        // Step 2: Determine which SSTables are NOT in the merge set
        Set<String> mergedPaths = new HashSet<>();
        for (SSTable sst : mergedSSTables) {
            mergedPaths.add(sst.path);
        }
        List<SSTable> unmergedSSTables = new ArrayList<>();
        for (SSTable sst : allSSTables) {
            if (!mergedPaths.contains(sst.path)) {
                unmergedSSTables.add(sst);
            }
        }

        // Step 3: Build result with tombstone purging
        List<Entry> result = new ArrayList<>();
        for (Entry winner : winners.values()) {
            if (winner.type == 'D') {
                long tombstoneAge = currentTime - winner.timestamp;
                if (tombstoneAge >= gcGraceSeconds) {
                    // Check overlap: can only purge if no unmerged SSTable
                    // has a key range covering this key
                    boolean canPurge = true;
                    for (SSTable sst : unmergedSSTables) {
                        if (sst.overlapsKey(winner.key)) {
                            canPurge = false;
                            break;
                        }
                    }
                    if (canPurge) {
                        continue; // purge this tombstone
                    }
                }
                result.add(winner);
            } else {
                result.add(winner);
            }
        }

        return result;
    }
}
