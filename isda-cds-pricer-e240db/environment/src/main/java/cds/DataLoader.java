package cds;

import java.io.*;
import java.util.*;

/**
 * Market data loader for CDS pricing pipeline.
 * Reads curve data from CSV files and trade definitions from JSON.
 *
 */
public class DataLoader {

    /**
     * Load a curve from CSV file.
     * Expected CSV format: header row "time,rate" followed by data rows.
     * Lines starting with '#' are treated as comments.
     *
     * @return double[2][] where [0] = times array, [1] = rates array
     */
    public static double[][] loadCurve(String path) throws Exception {
        var rows = new ArrayList<double[]>();
        var br = new BufferedReader(new FileReader(path));
        String line;
        var headerSkipped = false;
        while ((line = br.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            if (!headerSkipped) { headerSkipped = true; continue; }
            var parts = line.split(",");
            double time = Double.parseDouble(parts[1].trim());
            double rate = Double.parseDouble(parts[0].trim());
            rows.add(new double[]{time, rate});
        }
        br.close();
        var times = new double[rows.size()];
        var rates = new double[rows.size()];
        for (var i = 0; i < rows.size(); i++) {
            times[i] = rows.get(i)[0];
            rates[i] = rows.get(i)[1];
        }
        return new double[][]{times, rates};
    }

    /**
     * Load trade specifications from JSON configuration file.
     */
    public static List<Trade> loadTrades(String path) throws Exception {
        var sb = new StringBuilder();
        var br = new BufferedReader(new FileReader(path));
        String line;
        while ((line = br.readLine()) != null) sb.append(line).append("\n");
        br.close();
        var json = sb.toString();

        var trades = new ArrayList<Trade>();
        var valuationDate = extractString(json, "valuation_date");
        var stepinDate = extractString(json, "stepin_date");
        var recoveryRate = extractDouble(json, "recovery_rate");
        var notional = extractDouble(json, "notional");
        var fixedRate = extractDouble(json, "fixed_rate");

        var tradesStart = json.indexOf("\"trades\"");
        if (tradesStart < 0) return trades;
        var tradesSection = json.substring(tradesStart);

        var pos = 0;
        var braceDepth = 0;
        var inTradesArray = false;
        while (pos < tradesSection.length()) {
            var c = tradesSection.charAt(pos);
            if (c == '[' && !inTradesArray) { inTradesArray = true; pos++; continue; }
            if (!inTradesArray) { pos++; continue; }
            if (c == ']') break;
            if (c == '{') {
                var objEnd = tradesSection.indexOf("}", pos);
                if (objEnd < 0) break;
                var tradeJson = tradesSection.substring(pos, objEnd + 1);

                var t = new Trade();
                t.id = extractString(tradeJson, "id");
                t.buySell = extractString(tradeJson, "buy_sell").equals("BUY") ? 1 : -1;
                t.startDate = extractString(tradeJson, "start_date");
                t.endDate = extractString(tradeJson, "end_date");
                t.frequencyMonths = extractInt(tradeJson, "frequency_months");
                t.valuationDate = valuationDate;
                t.stepinDate = stepinDate;
                t.recoveryRate = recoveryRate;
                t.notional = notional;
                t.fixedRate = fixedRate;

                trades.add(t);
                pos = objEnd + 1;
            } else {
                pos++;
            }
        }
        return trades;
    }

    private static String extractString(String json, String key) {
        var pattern = "\"" + key + "\"";
        var idx = json.indexOf(pattern);
        if (idx < 0) return "";
        var colonIdx = json.indexOf(":", idx + pattern.length());
        var startQuote = json.indexOf("\"", colonIdx + 1);
        var endQuote = json.indexOf("\"", startQuote + 1);
        return json.substring(startQuote + 1, endQuote);
    }

    private static double extractDouble(String json, String key) {
        var pattern = "\"" + key + "\"";
        var idx = json.indexOf(pattern);
        if (idx < 0) return 0;
        var colonIdx = json.indexOf(":", idx + pattern.length());
        var start = colonIdx + 1;
        while (start < json.length() && (json.charAt(start) == ' ' || json.charAt(start) == '\n')) start++;
        var end = start;
        while (end < json.length() && (Character.isDigit(json.charAt(end)) || json.charAt(end) == '.'
                || json.charAt(end) == '-' || json.charAt(end) == 'E' || json.charAt(end) == 'e'
                || json.charAt(end) == '+')) end++;
        return Double.parseDouble(json.substring(start, end));
    }

    private static int extractInt(String json, String key) {
        return (int) extractDouble(json, key);
    }
}
