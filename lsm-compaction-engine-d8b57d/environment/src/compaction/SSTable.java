package compaction;

import java.io.*;
import java.util.*;


public class SSTable {
    public final String path;
    public int level;
    public long createdAt;
    public long sizeBytes;
    public String firstKey;
    public String lastKey;
    public double readHotness;
    private List<Entry> entries;

    public SSTable(String path) {
        this.path = path;
    }

    public void readMetadata() throws IOException {
        try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
            String metaLine = reader.readLine();
            if (metaLine != null) parseMetadata(metaLine);
        }
    }

    public List<Entry> readEntries() throws IOException {
        if (entries != null) return entries;
        entries = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
            String metaLine = reader.readLine();
            if (metaLine != null) parseMetadata(metaLine);
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (!line.isEmpty()) {
                    entries.add(Entry.fromLine(line));
                }
            }
        }
        return entries;
    }

    private void parseMetadata(String line) {
        // Format: #META level=0 created_at=1000 size_bytes=1024 first_key=aaa last_key=zzz read_hotness=0.5
        if (!line.startsWith("#META ")) return;
        String meta = line.substring(6);
        for (String part : meta.split(" ")) {
            String[] kv = part.split("=", 2);
            if (kv.length < 2) continue;
            switch (kv[0]) {
                case "level": level = Integer.parseInt(kv[1]); break;
                case "created_at": createdAt = Long.parseLong(kv[1]); break;
                case "size_bytes": sizeBytes = Long.parseLong(kv[1]); break;
                case "first_key": firstKey = kv[1]; break;
                case "last_key": lastKey = kv[1]; break;
                case "read_hotness": readHotness = Double.parseDouble(kv[1]); break;
            }
        }
    }

    public static void writeSSTable(String path, int level, long createdAt,
                                     List<Entry> entries) throws IOException {
        // Sort entries by key
        List<Entry> sorted = new ArrayList<>(entries);
        sorted.sort(Comparator.comparing(e -> e.key));

        String firstKey = sorted.isEmpty() ? "_" : sorted.get(0).key;
        String lastKey = sorted.isEmpty() ? "_" : sorted.get(sorted.size() - 1).key;
        long size = 0;
        for (Entry e : sorted) size += e.toLine().length();

        try (PrintWriter writer = new PrintWriter(new FileWriter(path))) {
            writer.println("#META level=" + level + " created_at=" + createdAt
                           + " size_bytes=" + size + " first_key=" + firstKey
                           + " last_key=" + lastKey + " read_hotness=0.0");
            for (Entry e : sorted) {
                writer.println(e.toLine());
            }
        }
    }

    public boolean overlapsKey(String key) {
        return firstKey != null && lastKey != null
               && firstKey.compareTo(key) <= 0
               && lastKey.compareTo(key) >= 0;
    }

    public boolean overlapsRange(String rangeFirst, String rangeLast) {
        return firstKey != null && lastKey != null
               && firstKey.compareTo(rangeLast) <= 0
               && lastKey.compareTo(rangeFirst) >= 0;
    }

    @Override
    public String toString() {
        return path;
    }
}
