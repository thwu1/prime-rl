package compaction;

import java.util.*;


/**
 * Implements compaction candidate selection for STCS and LCS strategies.
 */
public class CompactionSelector {

    /**
     * Size-Tiered Compaction Strategy candidate selection.
     * Groups SSTables into buckets by size similarity, selects the hottest
     * qualifying bucket, trims to maxThreshold keeping hottest SSTables.
     */
    public static List<SSTable> selectSTCS(List<SSTable> sstables,
                                            double bucketHigh, double bucketLow,
                                            long minSSTableSize,
                                            int minThreshold, int maxThreshold) {
        List<List<SSTable>> buckets = getBuckets(sstables, bucketHigh, bucketLow,
                                                  minSSTableSize);

        // Filter to qualifying buckets (>= minThreshold SSTables)
        List<List<SSTable>> qualifying = new ArrayList<>();
        for (List<SSTable> bucket : buckets) {
            if (bucket.size() >= minThreshold) {
                qualifying.add(bucket);
            }
        }

        if (qualifying.isEmpty()) return Collections.emptyList();

        // Select the bucket with the HIGHEST aggregate hotness
        List<SSTable> selected = null;
        double bestHotness = Double.NEGATIVE_INFINITY;
        for (List<SSTable> bucket : qualifying) {
            double hotness = 0;
            for (SSTable sst : bucket) hotness += sst.readHotness;
            if (hotness > bestHotness) {
                bestHotness = hotness;
                selected = new ArrayList<>(bucket);
            }
        }

        // Trim to maxThreshold, keeping the HOTTEST SSTables
        if (selected != null && selected.size() > maxThreshold) {
            // Sort descending by hotness, keep first maxThreshold
            selected.sort((a, b) -> Double.compare(b.readHotness, a.readHotness));
            selected = new ArrayList<>(selected.subList(0, maxThreshold));
        }

        return selected != null ? selected : Collections.emptyList();
    }

    /**
     * Group SSTables into buckets by size similarity.
     * An SSTable fits a bucket if its size is within [bucketLow*avg, bucketHigh*avg],
     * OR both the SSTable and the bucket avg are below minSSTableSize.
     */
    static List<List<SSTable>> getBuckets(List<SSTable> sstables,
                                           double bucketHigh, double bucketLow,
                                           long minSSTableSize) {
        List<SSTable> sorted = new ArrayList<>(sstables);
        sorted.sort(Comparator.comparingLong(s -> s.sizeBytes));

        Map<Long, List<SSTable>> buckets = new LinkedHashMap<>();

        outer:
        for (SSTable sst : sorted) {
            long size = sst.sizeBytes;

            for (Map.Entry<Long, List<SSTable>> entry
                    : new ArrayList<>(buckets.entrySet())) {
                List<SSTable> bucket = entry.getValue();
                long oldAvg = entry.getKey();

                if ((size > (oldAvg * bucketLow) && size < (oldAvg * bucketHigh))
                    || (size < minSSTableSize && oldAvg < minSSTableSize)) {
                    buckets.remove(oldAvg);
                    long totalSize = bucket.size() * oldAvg;
                    long newAvg = (totalSize + size) / (bucket.size() + 1);
                    bucket.add(sst);
                    buckets.put(newAvg, bucket);
                    continue outer;
                }
            }

            // No matching bucket found; create a new one
            List<SSTable> bucket = new ArrayList<>();
            bucket.add(sst);
            buckets.put(size, bucket);
        }

        return new ArrayList<>(buckets.values());
    }

    /**
     * Leveled Compaction Strategy candidate selection.
     * Finds the highest over-full level (score > 1.001), picks the SSTable
     * with the smallest first_key, and adds overlapping SSTables from the
     * next level.
     */
    public static List<SSTable> selectLCS(List<SSTable> allSSTables,
                                           long maxSSTableSizeMB,
                                           int fanoutSize) {
        long maxSSTableSizeBytes = maxSSTableSizeMB * 1024L * 1024L;

        // Group SSTables by level
        Map<Integer, List<SSTable>> levels = new TreeMap<>();
        for (SSTable sst : allSSTables) {
            levels.computeIfAbsent(sst.level, k -> new ArrayList<>()).add(sst);
        }

        int maxLevel = levels.keySet().stream()
                             .max(Integer::compareTo).orElse(0);

        // Find the HIGHEST level with score > 1.001 (scan high to low)
        for (int i = maxLevel; i >= 1; i--) {
            List<SSTable> levelSSTables =
                levels.getOrDefault(i, Collections.emptyList());
            if (levelSSTables.isEmpty()) continue;

            long totalBytes = 0;
            for (SSTable sst : levelSSTables) totalBytes += sst.sizeBytes;

            // Correct formula: fanout^level * maxSSTableSizeBytes
            long maxBytes = (long) Math.pow(fanoutSize, i) * maxSSTableSizeBytes;

            double score = (double) totalBytes / (double) maxBytes;

            if (score > 1.001) {
                // Sort by first_key and pick the first SSTable
                levelSSTables.sort(Comparator.comparing(s -> s.firstKey));
                SSTable candidate = levelSSTables.get(0);

                List<SSTable> result = new ArrayList<>();
                result.add(candidate);

                // Add all SSTables from the next level that overlap
                int nextLevel = i + 1;
                List<SSTable> nextLevelSSTables =
                    levels.getOrDefault(nextLevel, Collections.emptyList());
                for (SSTable nlsst : nextLevelSSTables) {
                    if (nlsst.overlapsRange(candidate.firstKey,
                                             candidate.lastKey)) {
                        result.add(nlsst);
                    }
                }

                return result;
            }
        }

        return Collections.emptyList();
    }
}
