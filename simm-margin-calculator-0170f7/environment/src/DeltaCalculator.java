import java.util.*;

/**
 * ISDA SIMM v2.6 Interest Rate Delta Margin Calculator.
 *
 * Computes the IR delta margin for a portfolio of bucketed rate sensitivities
 * using the ISDA Standard Initial Margin Model methodology.
 *
 */
public class DeltaCalculator {

    /** SIMM standard tenors */
    public static final String[] TENORS = {
        "2W", "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "15Y", "20Y", "30Y"
    };

    /** Year fractions corresponding to each tenor */
    public static final double[] TENOR_YEARS = {
        2.0 / 52.0,  // 2W
        1.0 / 12.0,  // 1M
        0.25,         // 3M
        0.5,          // 6M
        1.0,          // 1Y
        2.0,          // 2Y
        3.0,          // 3Y
        5.0,          // 5Y
        10.0,         // 10Y
        15.0,         // 15Y
        20.0,         // 20Y
        30.0          // 30Y
    };

    private final Map<String, double[]> riskWeights;
    private final Map<String, String> currencyGroups;
    private final Map<String, Double> concentrationThresholds;
    private final double theta;
    private final double rhoMin;
    private final double phi;
    private final double gamma;

    public DeltaCalculator(
            Map<String, double[]> riskWeights,
            Map<String, String> currencyGroups,
            Map<String, Double> concentrationThresholds,
            double theta, double rhoMin, double phi, double gamma) {
        this.riskWeights = riskWeights;
        this.currencyGroups = currencyGroups;
        this.concentrationThresholds = concentrationThresholds;
        this.theta = theta;
        this.rhoMin = rhoMin;
        this.phi = phi;
        this.gamma = gamma;
    }

    /**
     * Returns the index of the given tenor in the TENORS array.
     */
    public int tenorIndex(String tenor) {
        for (int i = 0; i < TENORS.length; i++) {
            if (TENORS[i].equals(tenor)) return i;
        }
        throw new IllegalArgumentException("Unknown tenor: " + tenor);
    }

    /**
     * Computes the parametric correlation between two tenors.
     * Uses the formula: max(exp(-theta * |Tk - Tl| / f(Tk, Tl)), rho_min)
     */
    public double tenorCorrelation(int k, int l) {
        if (k == l) return 1.0;
        double tk = TENOR_YEARS[k];
        double tl = TENOR_YEARS[l];
        return Math.max(
            Math.exp(-theta * Math.abs(tk - tl) / Math.max(tk, tl)),
            rhoMin
        );
    }

    /**
     * Returns the SIMM currency group for the given currency.
     * Defaults to HighVol for unmapped currencies.
     */
    public String getGroup(String currency) {
        return currencyGroups.getOrDefault(currency, "HighVol");
    }

    /**
     * Computes the ISDA SIMM v2.6 IR Delta Margin for the given portfolio.
     *
     * @param portfolio list of bucketed rate sensitivities
     * @return map with "buckets" (per-currency K, S, CR) and "deltaMargin"
     */
    public Map<String, Object> computeDeltaMargin(List<Sensitivity> portfolio) {
        if (portfolio.isEmpty()) {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("buckets", new LinkedHashMap<>());
            result.put("deltaMargin", 0.0);
            return result;
        }

        // Group sensitivities by currency (each currency is a "bucket")
        Map<String, List<Sensitivity>> buckets = new LinkedHashMap<>();
        for (Sensitivity s : portfolio) {
            buckets.computeIfAbsent(s.currency, k -> new ArrayList<>()).add(s);
        }

        Map<String, Map<String, Double>> bucketResults = new LinkedHashMap<>();

        for (Map.Entry<String, List<Sensitivity>> entry : buckets.entrySet()) {
            String ccy = entry.getKey();
            List<Sensitivity> sensList = entry.getValue();

            String group = getGroup(ccy);
            double[] rw = riskWeights.get(group);
            double threshold = concentrationThresholds.get(group);

            // Step 1: Concentration Risk Factor
            double netSens = 0;
            for (Sensitivity s : sensList) {
                netSens += s.value;
            }
            double cr = Math.max(1.0, Math.abs(netSens) / threshold);

            // Step 2: Weighted Sensitivities
            int n = sensList.size();
            double[] ws = new double[n];
            int[] tenorIdx = new int[n];
            String[] subCurves = new String[n];
            for (int i = 0; i < n; i++) {
                tenorIdx[i] = tenorIndex(sensList.get(i).tenor);
                subCurves[i] = sensList.get(i).subCurve;
                ws[i] = rw[tenorIdx[i]] * sensList.get(i).value * cr;
            }

            // Step 3: Intra-bucket aggregation
            double kSquared = 0;
            for (int i = 0; i < n; i++) {
                for (int j = 0; j < n; j++) {
                    double rho = tenorCorrelation(tenorIdx[i], tenorIdx[j]);
                    double phiFactor = 1.0;
                    kSquared += rho * phiFactor * ws[i] * ws[j];
                }
            }
            double K = Math.sqrt(Math.max(0, kSquared));

            // Sum of weighted sensitivities
            double S = 0;
            for (double w : ws) S += w;

            Map<String, Double> result = new LinkedHashMap<>();
            result.put("K", K);
            result.put("S", S);
            result.put("CR", cr);
            bucketResults.put(ccy, result);
        }

        // Step 4: Inter-bucket aggregation
        List<String> ccys = new ArrayList<>(bucketResults.keySet());
        Collections.sort(ccys);

        double deltaMargin;
        if (ccys.size() == 1) {
            deltaMargin = bucketResults.get(ccys.get(0)).get("K");
        } else {
            double total = 0;
            for (String ccy : ccys) {
                double K = bucketResults.get(ccy).get("K");
                total += K * K;
            }
            for (int i = 0; i < ccys.size(); i++) {
                for (int j = i + 1; j < ccys.size(); j++) {
                    double si = bucketResults.get(ccys.get(i)).get("S");
                    double sj = bucketResults.get(ccys.get(j)).get("S");
                    total += 2 * gamma * si * sj;
                }
            }

            if (total < 0) {
                // Recompute with capped S values
                total = 0;
                for (String ccy : ccys) {
                    double K = bucketResults.get(ccy).get("K");
                    total += K * K;
                }
                for (int i = 0; i < ccys.size(); i++) {
                    for (int j = i + 1; j < ccys.size(); j++) {
                        double Ki = bucketResults.get(ccys.get(i)).get("K");
                        double si = bucketResults.get(ccys.get(i)).get("S");
                        double siCapped = Math.max(-Ki, Math.min(si, Ki));
                        double Kj = bucketResults.get(ccys.get(j)).get("K");
                        double sj = bucketResults.get(ccys.get(j)).get("S");
                        double sjCapped = Math.max(-Kj, Math.min(sj, Kj));
                        total += 2 * gamma * siCapped * sjCapped;
                    }
                }
            }

            deltaMargin = Math.sqrt(Math.max(0, total));
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("buckets", bucketResults);
        result.put("deltaMargin", deltaMargin);
        return result;
    }
}
