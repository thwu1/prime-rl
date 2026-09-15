package compaction;

import java.io.*;
import java.util.*;


public class Main {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println(
                "Usage: java compaction.Main <merge|select-stcs|select-lcs> <config>");
            System.exit(1);
        }

        String command = args[0];
        Config config = Config.load(args[1]);

        switch (command) {
            case "merge":
                doMerge(config);
                break;
            case "select-stcs":
                doSelectSTCS(config);
                break;
            case "select-lcs":
                doSelectLCS(config);
                break;
            default:
                System.err.println("Unknown command: " + command);
                System.exit(1);
        }
    }

    static void doMerge(Config config) throws IOException {
        List<SSTable> mergedSSTables = new ArrayList<>();
        List<List<Entry>> allEntries = new ArrayList<>();

        for (String path : config.sstablePaths) {
            SSTable sst = new SSTable(path.trim());
            allEntries.add(sst.readEntries());
            mergedSSTables.add(sst);
        }

        List<SSTable> allSSTables = new ArrayList<>();
        for (String path : config.allSstablePaths) {
            SSTable sst = new SSTable(path.trim());
            sst.readMetadata();
            allSSTables.add(sst);
        }

        List<Entry> merged = MergeEngine.merge(
            allEntries, mergedSSTables, allSSTables,
            config.currentTime, config.gcGraceSeconds);

        SSTable.writeSSTable(config.outputPath, 0, config.currentTime, merged);
    }

    static void doSelectSTCS(Config config) throws IOException {
        List<SSTable> sstables = new ArrayList<>();
        for (String path : config.allSstablePaths) {
            SSTable sst = new SSTable(path.trim());
            sst.readMetadata();
            sstables.add(sst);
        }

        List<SSTable> selected = CompactionSelector.selectSTCS(
            sstables,
            config.stcsBucketHigh, config.stcsBucketLow,
            config.stcsMinSSTableSize,
            config.stcsMinThreshold, config.stcsMaxThreshold);

        for (SSTable sst : selected) {
            System.out.println(sst.path);
        }
    }

    static void doSelectLCS(Config config) throws IOException {
        List<SSTable> sstables = new ArrayList<>();
        for (String path : config.allSstablePaths) {
            SSTable sst = new SSTable(path.trim());
            sst.readMetadata();
            sstables.add(sst);
        }

        List<SSTable> selected = CompactionSelector.selectLCS(
            sstables,
            config.lcsMaxSSTableSizeMB, config.lcsFanoutSize);

        for (SSTable sst : selected) {
            System.out.println(sst.path);
        }
    }
}
