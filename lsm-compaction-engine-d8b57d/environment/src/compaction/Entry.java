package compaction;


public class Entry implements Comparable<Entry> {
    public final String key;
    public final long timestamp;
    public final char type; // 'V' = value, 'D' = delete tombstone, 'T' = TTL value
    public final String value;
    public final long ttl; // seconds, only meaningful for type 'T'

    public Entry(String key, long timestamp, char type, String value, long ttl) {
        this.key = key;
        this.timestamp = timestamp;
        this.type = type;
        this.value = value;
        this.ttl = ttl;
    }

    @Override
    public int compareTo(Entry other) {
        return this.key.compareTo(other.key);
    }

    public String toLine() {
        return key + "\t" + timestamp + "\t" + type + "\t"
               + (value != null ? value : "") + "\t" + ttl;
    }

    public static Entry fromLine(String line) {
        String[] parts = line.split("\t", -1);
        String key = parts[0];
        long timestamp = Long.parseLong(parts[1]);
        char type = parts[2].charAt(0);
        String value = parts[3].isEmpty() ? null : parts[3];
        long ttl = Long.parseLong(parts[4]);
        return new Entry(key, timestamp, type, value, ttl);
    }

    @Override
    public String toString() {
        return "Entry{key=" + key + ", ts=" + timestamp + ", type=" + type
               + ", val=" + value + ", ttl=" + ttl + "}";
    }
}
