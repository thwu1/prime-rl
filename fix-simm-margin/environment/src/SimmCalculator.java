import java.io.*;
import java.math.*;
import java.util.*;
import java.util.stream.*;

/**
 * ISDA SIMM v2.5 1-Day Delta Margin Calculator.
 * Reads a CRIF portfolio CSV and outputs margin results as JSON.
 *
 */
public class SimmCalculator {

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: SimmCalculator <portfolio.csv> [filter_risk_types]");
            System.exit(1);
        }
        List<String[]> records = parseCsv(args[0]);

        // Optional filter: comma-separated risk types to include
        if (args.length > 1 && !args[1].isEmpty()) {
            Set<String> types = new HashSet<>(Arrays.asList(args[1].split(",")));
            records = records.stream()
                .filter(r -> types.contains(r[1]))
                .collect(Collectors.toList());
        }

        BigDecimal total = SimmEngine.computeTotal(records);
        System.out.println(total.toBigInteger().toString());
    }

    /**
     * Parse CRIF CSV. Returns list of String arrays:
     * [0]=ProductClass, [1]=RiskType, [2]=Qualifier, [3]=Bucket,
     * [4]=Label1, [5]=Label2, [6]=AmountUSD
     */
    static List<String[]> parseCsv(String path) throws IOException {
        List<String[]> records = new ArrayList<>();
        try (BufferedReader br = new BufferedReader(new FileReader(path))) {
            String line = br.readLine(); // skip header
            while ((line = br.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty()) continue;
                String[] parts = line.split(",", -1);
                if (parts.length < 7) {
                    // pad with empty strings
                    String[] padded = new String[7];
                    System.arraycopy(parts, 0, padded, 0, parts.length);
                    for (int i = parts.length; i < 7; i++) padded[i] = "";
                    parts = padded;
                }
                records.add(parts);
            }
        }
        return records;
    }
}
