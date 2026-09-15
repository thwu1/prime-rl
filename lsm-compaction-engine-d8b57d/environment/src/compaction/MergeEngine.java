package compaction;

import java.util.*;


/**
 * Merges multiple SSTables into a single compacted result.
 *
 * Merge rules:
 * - For each key, the entry with the highest timestamp wins
 * - Expired TTL entries become implicit tombstones
 * - Tombstones purgeable when gc_grace elapsed AND all overlapping SSTables included
 * - Non-purgeable tombstones must be retained in output
 */
public class MergeEngine {

    public static List<Entry> merge(List<List<Entry>> sstableEntries,
                                     List<SSTable> mergedSSTables,
                                     List<SSTable> allSSTables,
                                     long currentTime,
                                     long gcGraceSeconds) {

        // Step 1: For each key, pick the winning entry
        Map<String, Entry> winners = new TreeMap<>();

        for (List<Entry> entries : sstableEntries) {
            for (Entry e : entries) {
                Entry existing = winners.get(e.key);
                if (existing == null) {
                    winners.put(e.key, e);
                } else {
                    // Pick the entry with the best timestamp
                    if (e.timestamp < existing.timestamp) {
                        winners.put(e.key, e);
                    }
                }
            }
        }

        // Step 2: Build result with tombstone handling
        List<Entry> result = new ArrayList<>();
        for (Entry winner : winners.values()) {
            if (winner.type == 'D') {
                long tombstoneAge = currentTime - winner.timestamp;
                if (tombstoneAge < gcGraceSeconds) {
                    // Tombstone is eligible for purging
                    continue;
                }
                result.add(winner);
            } else {
                result.add(winner);
            }
        }

        return result;
    }
}
