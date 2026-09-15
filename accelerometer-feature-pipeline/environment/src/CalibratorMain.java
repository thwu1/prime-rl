import java.io.*;
import java.util.*;

/**
 * CLI driver for sensor calibration.
 * Reads raw accelerometer CSV, applies calibration correction using parameters
 * from a properties file, writes calibrated CSV output.
 *
 * Usage: CalibratorMain <input.csv> <output.csv> <calibration.properties>
 */
public class CalibratorMain {

    public static void main(String[] args) throws Exception {
        if (args.length < 3) {
            System.err.println("Usage: CalibratorMain <input.csv> <output.csv> <calibration.properties>");
            System.exit(1);
        }

        String inputFile = args[0];
        String outputFile = args[1];
        String configFile = args[2];

        // Read calibration parameters
        Properties props = new Properties();
        props.load(new FileInputStream(configFile));

        double[] offset = {
            Double.parseDouble(props.getProperty("offset.x")),
            Double.parseDouble(props.getProperty("offset.y")),
            Double.parseDouble(props.getProperty("offset.z"))
        };
        double[] scale = {
            Double.parseDouble(props.getProperty("scale.x")),
            Double.parseDouble(props.getProperty("scale.y")),
            Double.parseDouble(props.getProperty("scale.z"))
        };

        // Read raw data
        List<double[]> rows = new ArrayList<>();
        BufferedReader reader = new BufferedReader(new FileReader(inputFile));
        String line;
        while ((line = reader.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty()) continue;
            try {
                String[] parts = line.split(",");
                rows.add(new double[]{
                    Double.parseDouble(parts[0].trim()),
                    Double.parseDouble(parts[1].trim()),
                    Double.parseDouble(parts[2].trim())
                });
            } catch (NumberFormatException e) {
                continue;
            }
        }
        reader.close();

        if (rows.isEmpty()) {
            System.err.println("Error: no data rows in " + inputFile);
            System.exit(1);
        }

        int n = rows.size();
        double[] x = new double[n];
        double[] y = new double[n];
        double[] z = new double[n];
        for (int i = 0; i < n; i++) {
            x[i] = rows.get(i)[0];
            y[i] = rows.get(i)[1];
            z[i] = rows.get(i)[2];
        }

        // Apply calibration
        Calibrator cal = new Calibrator(offset, scale);
        cal.apply(x, y, z);

        // Write calibrated data
        File parent = new File(outputFile).getParentFile();
        if (parent != null) parent.mkdirs();

        BufferedWriter writer = new BufferedWriter(new FileWriter(outputFile));
        for (int i = 0; i < n; i++) {
            writer.write(String.format("%.17g,%.17g,%.17g", x[i], y[i], z[i]));
            writer.newLine();
        }
        writer.close();

        double err = Calibrator.computeResidualError(x, y, z);
        System.out.printf("Calibrated %d samples (residual: %.6f) -> %s%n", n, err, outputFile);
    }
}
