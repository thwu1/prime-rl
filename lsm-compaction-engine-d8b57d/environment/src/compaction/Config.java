package compaction;

import java.io.*;
import java.util.*;


public class Config {
    public List<String> sstablePaths = new ArrayList<>();
    public List<String> allSstablePaths = new ArrayList<>();
    public long gcGraceSeconds = 86400;
    public long currentTime = 0;
    public String outputPath = "output.sst";

    // STCS params
    public double stcsBucketHigh = 1.5;
    public double stcsBucketLow = 0.5;
    public long stcsMinSSTableSize = 50;
    public int stcsMinThreshold = 4;
    public int stcsMaxThreshold = 32;

    // LCS params
    public long lcsMaxSSTableSizeMB = 160;
    public int lcsFanoutSize = 10;

    public static Config load(String path) throws IOException {
        Config config = new Config();
        try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                int eq = line.indexOf('=');
                if (eq < 0) continue;
                String key = line.substring(0, eq).trim();
                String val = line.substring(eq + 1).trim();
                switch (key) {
                    case "sstables":
                        config.sstablePaths = Arrays.asList(val.split(","));
                        break;
                    case "all_sstables":
                        config.allSstablePaths = Arrays.asList(val.split(","));
                        break;
                    case "gc_grace_seconds":
                        config.gcGraceSeconds = Long.parseLong(val);
                        break;
                    case "current_time":
                        config.currentTime = Long.parseLong(val);
                        break;
                    case "output":
                        config.outputPath = val;
                        break;
                    case "stcs.bucket_high":
                        config.stcsBucketHigh = Double.parseDouble(val);
                        break;
                    case "stcs.bucket_low":
                        config.stcsBucketLow = Double.parseDouble(val);
                        break;
                    case "stcs.min_sstable_size":
                        config.stcsMinSSTableSize = Long.parseLong(val);
                        break;
                    case "stcs.min_threshold":
                        config.stcsMinThreshold = Integer.parseInt(val);
                        break;
                    case "stcs.max_threshold":
                        config.stcsMaxThreshold = Integer.parseInt(val);
                        break;
                    case "lcs.max_sstable_size_mb":
                        config.lcsMaxSSTableSizeMB = Long.parseLong(val);
                        break;
                    case "lcs.fanout_size":
                        config.lcsFanoutSize = Integer.parseInt(val);
                        break;
                }
            }
        }
        return config;
    }
}
