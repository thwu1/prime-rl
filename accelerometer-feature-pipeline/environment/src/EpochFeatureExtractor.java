import java.io.*;
import java.util.*;

/**
 * CLI driver for epoch-level accelerometer feature extraction.
 * Reads raw triaxial data from CSV, computes features, writes JSON output.
 *
 * Usage: EpochFeatureExtractor <input.csv> <output.json>
 *
 * Input CSV: no header, columns x,y,z (accelerometer readings in g-units, 100 Hz)
 * Output JSON: feature name -> numeric value
 */
public class EpochFeatureExtractor {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: EpochFeatureExtractor <input.csv> <output.json>");
            System.exit(1);
        }

        String inputFile = args[0];
        String outputFile = args[1];
        int sampleRate = 100;

        // Read CSV (no header, columns: x, y, z)
        List<double[]> rows = new ArrayList<>();
        BufferedReader reader = new BufferedReader(new FileReader(inputFile));
        String line;
        while ((line = reader.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty()) continue;
            // Skip header if present
            try {
                String[] parts = line.split(",");
                double x = Double.parseDouble(parts[0].trim());
                double y = Double.parseDouble(parts[1].trim());
                double z = Double.parseDouble(parts[2].trim());
                rows.add(new double[]{x, y, z});
            } catch (NumberFormatException e) {
                // Skip non-numeric lines (headers)
                continue;
            }
        }
        reader.close();

        if (rows.isEmpty()) {
            System.err.println("Error: no data rows found in " + inputFile);
            System.exit(1);
        }

        int n = rows.size();
        double[] xArr = new double[n];
        double[] yArr = new double[n];
        double[] zArr = new double[n];
        for (int i = 0; i < n; i++) {
            xArr[i] = rows.get(i)[0];
            yArr[i] = rows.get(i)[1];
            zArr[i] = rows.get(i)[2];
        }

        System.out.println("Read " + n + " samples from " + inputFile);

        // Create 4th-order Butterworth low-pass filter at 20 Hz
        LowpassFilter filter = new LowpassFilter(20, sampleRate);

        // Compute features (with filter and feature extraction enabled)
        double[] stats = AccStats.getAccStats(xArr, yArr, zArr, filter, true, sampleRate);
        String header = AccStats.getStatsHeader(true);
        String[] names = header.split(",");

        int numFeatures = Math.min(names.length, stats.length);

        // Write output as JSON
        File parentDir = new File(outputFile).getParentFile();
        if (parentDir != null) parentDir.mkdirs();

        BufferedWriter writer = new BufferedWriter(new FileWriter(outputFile));
        writer.write("{\n");
        for (int i = 0; i < numFeatures; i++) {
            String val;
            if (Double.isNaN(stats[i])) {
                val = "null";
            } else if (Double.isInfinite(stats[i])) {
                val = "null";
            } else {
                val = String.valueOf(stats[i]);
            }
            writer.write("  \"" + names[i] + "\": " + val);
            if (i < numFeatures - 1) writer.write(",");
            writer.write("\n");
        }
        writer.write("}\n");
        writer.close();

        System.out.println("Computed " + numFeatures + " features -> " + outputFile);
    }
}
