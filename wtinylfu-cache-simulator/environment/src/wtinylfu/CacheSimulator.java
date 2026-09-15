package wtinylfu;

import java.io.*;
import java.util.*;

public class CacheSimulator {
    public static void main(String[] args) throws Exception {
        if (args.length != 4) {
            System.err.println("Usage: CacheSimulator <trace_file> <max_size> <percent_main> <percent_main_protected>");
            System.exit(1);
        }

        String traceFile = args[0];
        int maxSize = Integer.parseInt(args[1]);
        double percentMain = Double.parseDouble(args[2]);
        double percentMainProtected = Double.parseDouble(args[3]);

        WTinyLfuCache cache = new WTinyLfuCache(maxSize, percentMainProtected, percentMain);

        try (BufferedReader reader = new BufferedReader(new FileReader(traceFile))) {
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty()) continue;
                long key = Long.parseLong(line);
                cache.access(key);
            }
        }

        System.out.println("{");
        System.out.println("  \"hit_count\": " + cache.getHitCount() + ",");
        System.out.println("  \"miss_count\": " + cache.getMissCount() + ",");
        System.out.println("  \"eviction_count\": " + cache.getEvictionCount() + ",");
        System.out.println("  \"cache_size\": " + cache.getCacheSize() + ",");
        System.out.println("  \"window_keys\": " + toJson(cache.getWindowKeys()) + ",");
        System.out.println("  \"probation_keys\": " + toJson(cache.getProbationKeys()) + ",");
        System.out.println("  \"protected_keys\": " + toJson(cache.getProtectedKeys()));
        System.out.println("}");
    }

    private static String toJson(List<Long> list) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < list.size(); i++) {
            if (i > 0) sb.append(", ");
            sb.append(list.get(i));
        }
        sb.append("]");
        return sb.toString();
    }
}
