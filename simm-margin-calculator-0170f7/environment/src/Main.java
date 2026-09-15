import java.io.*;
import java.util.*;

/**
 * CLI entry point for ISDA SIMM v2.6 IR Margin Calculator.
 * Reads portfolio CSV and SIMM parameter files, computes delta margin,
 * curvature margin, and total IR margin, then outputs JSON.
 *
 */
public class Main {

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            System.err.println("Usage: java Main <portfolio_csv>");
            System.exit(1);
        }

        String portfolioPath = args[0];

        // Load SIMM parameters
        Map<String, double[]> riskWeights = loadRiskWeights("/app/data/risk_weights.csv");
        Map<String, String> currencyGroups = loadCurrencyGroups("/app/data/currency_groups.csv");
        Map<String, Double> thresholds = loadThresholds("/app/data/concentration_thresholds.csv");
        Map<String, Double> simmParams = loadScalarParams("/app/data/simm_params.csv");
        Map<String, Double> curvatureParams = loadScalarParams("/app/data/curvature_params.csv");

        // Load and split portfolio by risk type
        List<Sensitivity> portfolio = loadPortfolio(portfolioPath);
        List<Sensitivity> deltaSens = new ArrayList<>();
        List<Sensitivity> curvatureSens = new ArrayList<>();
        for (Sensitivity s : portfolio) {
            if ("Delta".equals(s.riskType)) {
                deltaSens.add(s);
            } else if ("Curvature".equals(s.riskType)) {
                curvatureSens.add(s);
            }
        }

        // Compute delta margin
        DeltaCalculator deltaCalc = new DeltaCalculator(
            riskWeights, currencyGroups, thresholds,
            simmParams.get("theta"),
            simmParams.get("rho_min"),
            simmParams.get("phi"),
            simmParams.get("gamma")
        );
        Map<String, Object> deltaResult = deltaCalc.computeDeltaMargin(deltaSens);

        // Compute curvature margin
        CurvatureCalculator curvCalc = new CurvatureCalculator(
            riskWeights, currencyGroups,
            simmParams.get("theta"),
            simmParams.get("rho_min"),
            simmParams.get("phi"),
            simmParams.get("gamma"),
            curvatureParams.get("sigma")
        );
        Map<String, Object> curvatureResult = curvCalc.computeCurvatureMargin(curvatureSens);

        // Compute total IR margin
        RiskAggregator aggregator = new RiskAggregator(
            curvatureParams.get("rho_delta_curvature")
        );
        double totalMargin = aggregator.computeTotalMargin(
            (Double) deltaResult.get("deltaMargin"),
            (Double) curvatureResult.get("curvatureMargin")
        );

        // Format and output JSON
        System.out.println(formatJson(deltaResult, curvatureResult, totalMargin));
    }

    static Map<String, double[]> loadRiskWeights(String path) throws IOException {
        Map<String, double[]> weights = new LinkedHashMap<>();
        try (BufferedReader br = new BufferedReader(new FileReader(path))) {
            String header = br.readLine();
            String line;
            while ((line = br.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                String[] parts = line.split(",");
                String group = parts[0].trim();
                double[] vals = new double[parts.length - 1];
                for (int i = 1; i < parts.length; i++) {
                    vals[i - 1] = Double.parseDouble(parts[i].trim());
                }
                weights.put(group, vals);
            }
        }
        return weights;
    }

    static Map<String, String> loadCurrencyGroups(String path) throws IOException {
        Map<String, String> groups = new LinkedHashMap<>();
        try (BufferedReader br = new BufferedReader(new FileReader(path))) {
            br.readLine();
            String line;
            while ((line = br.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                String[] parts = line.split(",");
                groups.put(parts[0].trim(), parts[1].trim());
            }
        }
        return groups;
    }

    static Map<String, Double> loadThresholds(String path) throws IOException {
        Map<String, Double> thresholds = new LinkedHashMap<>();
        try (BufferedReader br = new BufferedReader(new FileReader(path))) {
            br.readLine();
            String line;
            while ((line = br.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                String[] parts = line.split(",");
                thresholds.put(parts[0].trim(), Double.parseDouble(parts[1].trim()));
            }
        }
        return thresholds;
    }

    static Map<String, Double> loadScalarParams(String path) throws IOException {
        Map<String, Double> params = new LinkedHashMap<>();
        try (BufferedReader br = new BufferedReader(new FileReader(path))) {
            br.readLine();
            String line;
            while ((line = br.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                String[] parts = line.split(",");
                params.put(parts[0].trim(), Double.parseDouble(parts[1].trim()));
            }
        }
        return params;
    }

    static List<Sensitivity> loadPortfolio(String path) throws IOException {
        List<Sensitivity> portfolio = new ArrayList<>();
        try (BufferedReader br = new BufferedReader(new FileReader(path))) {
            br.readLine(); // skip header
            String line;
            while ((line = br.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                String[] parts = line.split(",");
                portfolio.add(new Sensitivity(
                    parts[0].trim(),  // riskType
                    parts[1].trim(),  // currency
                    parts[2].trim(),  // subCurve
                    parts[3].trim(),  // tenor
                    Double.parseDouble(parts[4].trim())  // value
                ));
            }
        }
        return portfolio;
    }

    @SuppressWarnings("unchecked")
    static String formatJson(Map<String, Object> deltaResult,
                             Map<String, Object> curvatureResult,
                             double totalMargin) {
        StringBuilder sb = new StringBuilder();
        sb.append("{");

        // Delta buckets
        Map<String, Map<String, Double>> deltaBuckets =
            (Map<String, Map<String, Double>>) deltaResult.get("buckets");
        sb.append("\"deltaBuckets\":{");
        List<String> dccys = new ArrayList<>(deltaBuckets.keySet());
        Collections.sort(dccys);
        for (int i = 0; i < dccys.size(); i++) {
            String ccy = dccys.get(i);
            Map<String, Double> br = deltaBuckets.get(ccy);
            sb.append("\"").append(ccy).append("\":{");
            sb.append("\"K\":").append(String.format("%.6f", br.get("K"))).append(",");
            sb.append("\"S\":").append(String.format("%.6f", br.get("S"))).append(",");
            sb.append("\"CR\":").append(String.format("%.6f", br.get("CR")));
            sb.append("}");
            if (i < dccys.size() - 1) sb.append(",");
        }
        sb.append("},");

        // Delta margin
        sb.append("\"deltaMargin\":").append(String.format("%.6f", deltaResult.get("deltaMargin"))).append(",");

        // Curvature buckets
        Map<String, Map<String, Double>> curvBuckets =
            (Map<String, Map<String, Double>>) curvatureResult.get("buckets");
        sb.append("\"curvatureBuckets\":{");
        List<String> cccys = new ArrayList<>(curvBuckets.keySet());
        Collections.sort(cccys);
        for (int i = 0; i < cccys.size(); i++) {
            String ccy = cccys.get(i);
            Map<String, Double> br = curvBuckets.get(ccy);
            sb.append("\"").append(ccy).append("\":{");
            sb.append("\"K\":").append(String.format("%.6f", br.get("K"))).append(",");
            sb.append("\"sumCVR\":").append(String.format("%.6f", br.get("sumCVR"))).append(",");
            sb.append("\"lambda\":").append(String.format("%.6f", br.get("lambda"))).append(",");
            sb.append("\"margin\":").append(String.format("%.6f", br.get("margin")));
            sb.append("}");
            if (i < cccys.size() - 1) sb.append(",");
        }
        sb.append("},");

        // Curvature margin
        sb.append("\"curvatureMargin\":").append(String.format("%.6f", curvatureResult.get("curvatureMargin"))).append(",");

        // Total margin
        sb.append("\"totalMargin\":").append(String.format("%.6f", totalMargin));

        sb.append("}");
        return sb.toString();
    }
}
