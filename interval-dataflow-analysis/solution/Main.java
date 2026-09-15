package dataflow;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import java.io.FileWriter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class Main {
    public static void main(String[] args) throws Exception {
        if (args.length < 1 || args.length > 2) {
            System.err.println("Usage: java dataflow.Main <cfg-file> [json-output]");
            System.exit(1);
        }
        CFG cfg = CfgParser.parse(args[0]);

        IntervalAnalyzer analyzer = new IntervalAnalyzer(cfg);
        analyzer.analyze();

        Map<String, IntervalStore> entryMap = analyzer.getBlockEntry();
        Map<String, IntervalStore> exitMap = analyzer.getBlockExit();

        List<String> vars = cfg.variables; // already sorted

        // Build results for both text and JSON output
        Map<String, Map<String, Map<String, String>>> analysis = new LinkedHashMap<>();

        for (String blockId : cfg.blockOrder) {
            IntervalStore entry = entryMap.get(blockId);
            IntervalStore exit = exitMap.get(blockId);

            Map<String, String> entryData = new LinkedHashMap<>();
            Map<String, String> exitData = new LinkedHashMap<>();

            for (String var : vars) {
                String entryVal = (entry != null) ? entry.get(var).toString() : "bot";
                entryData.put(var, entryVal);
                System.out.println(blockId + " entry " + var + " " + entryVal);
            }
            for (String var : vars) {
                String exitVal = (exit != null) ? exit.get(var).toString() : "bot";
                exitData.put(var, exitVal);
                System.out.println(blockId + " exit " + var + " " + exitVal);
            }

            Map<String, Map<String, String>> blockData = new LinkedHashMap<>();
            blockData.put("entry", entryData);
            blockData.put("exit", exitData);
            analysis.put(blockId, blockData);
        }

        // Write JSON output if path provided
        if (args.length >= 2) {
            Map<String, Object> root = new LinkedHashMap<>();
            root.put("analysis", analysis);
            Gson gson = new GsonBuilder().setPrettyPrinting().create();
            try (FileWriter fw = new FileWriter(args[1])) {
                gson.toJson(root, fw);
            }
        }
    }
}
