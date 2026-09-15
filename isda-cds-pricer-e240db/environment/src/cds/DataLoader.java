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
        List<double[]> rows = new ArrayList<>();
        BufferedReader br = new BufferedReader(new FileReader(path));
        String line;
        boolean headerSkipped = false;
        while ((line = br.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            if (!headerSkipped) { headerSkipped = true; continue; }
            String[] parts = line.split(",");
            double time = Double.parseDouble(parts[1].trim());
            double rate = Double.parseDouble(parts[0].trim());
            rows.add(new double[]{time, rate});
        }
        br.close();
        double[] times = new double[rows.size()];
        double[] rates = new double[rows.size()];
        for (int i = 0; i < rows.size(); i++) {
            times[i] = rows.get(i)[0];
            rates[i] = rows.get(i)[1];
        }
        return new double[][]{times, rates};
    }

    /**
     * Load trade specifications from JSON configuration file.
     */
    public static List<Trade> loadTrades(String path) throws Exception {
        StringBuilder sb = new StringBuilder();
        BufferedReader br = new BufferedReader(new FileReader(path));
        String line;
        while ((line = br.readLine()) != null) sb.append(line).append("\n");
        br.close();
        String json = sb.toString();

        List<Trade> trades = new ArrayList<>();
        String valuationDate = extractString(json, "valuation_date");
        String stepinDate = extractString(json, "stepin_date");
        double recoveryRate = extractDouble(json, "recovery_rate");
        double notional = extractDouble(json, "notional");
        double fixedRate = extractDouble(json, "fixed_rate");

        int tradesStart = json.indexOf("\"trades\"");
        if (tradesStart < 0) return trades;
        String tradesSection = json.substring(tradesStart);

        int pos = 0;
        int braceDepth = 0;
        boolean inTradesArray = false;
        while (pos < tradesSection.length()) {
            char c = tradesSection.charAt(pos);
            if (c == '[' && !inTradesArray) { inTradesArray = true; pos++; continue; }
            if (!inTradesArray) { pos++; continue; }
            if (c == ']') break;
            if (c == '{') {
                int objEnd = tradesSection.indexOf("}", pos);
                if (objEnd < 0) break;
                String tradeJson = tradesSection.substring(pos, objEnd + 1);

                Trade t = new Trade();
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
        String pattern = "\"" + key + "\"";
        int idx = json.indexOf(pattern);
        if (idx < 0) return "";
        int colonIdx = json.indexOf(":", idx + pattern.length());
        int startQuote = json.indexOf("\"", colonIdx + 1);
        int endQuote = json.indexOf("\"", startQuote + 1);
        return json.substring(startQuote + 1, endQuote);
    }

    private static double extractDouble(String json, String key) {
        String pattern = "\"" + key + "\"";
        int idx = json.indexOf(pattern);
        if (idx < 0) return 0;
        int colonIdx = json.indexOf(":", idx + pattern.length());
        int start = colonIdx + 1;
        while (start < json.length() && (json.charAt(start) == ' ' || json.charAt(start) == '\n')) start++;
        int end = start;
        while (end < json.length() && (Character.isDigit(json.charAt(end)) || json.charAt(end) == '.'
                || json.charAt(end) == '-' || json.charAt(end) == 'E' || json.charAt(end) == 'e'
                || json.charAt(end) == '+')) end++;
        return Double.parseDouble(json.substring(start, end));
    }

    private static int extractInt(String json, String key) {
        return (int) extractDouble(json, key);
    }
}
