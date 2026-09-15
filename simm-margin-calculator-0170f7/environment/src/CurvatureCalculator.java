import java.util.*;

/**
 * ISDA SIMM v2.6 Interest Rate Curvature Margin Calculator.
 *
 * Computes the IR curvature margin for a portfolio of vega sensitivities
 * using the CVR (curvature value-at-risk) approach. See ir_curvature_spec.txt
 * for the full methodology.
 *
 */
public class CurvatureCalculator {

    public static final String[] TENORS = {
        "2W", "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "15Y", "20Y", "30Y"
    };

    public static final double[] TENOR_YEARS = {
        2.0 / 52.0, 1.0 / 12.0, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0,
        10.0, 15.0, 20.0, 30.0
    };

    private final Map<String, double[]> riskWeights;
    private final Map<String, String> currencyGroups;
    private final double theta;
    private final double rhoMin;
    private final double phi;
    private final double gamma;
    private final double sigma;

    public CurvatureCalculator(
            Map<String, double[]> riskWeights,
            Map<String, String> currencyGroups,
            double theta, double rhoMin, double phi, double gamma,
            double sigma) {
        this.riskWeights = riskWeights;
        this.currencyGroups = currencyGroups;
        this.theta = theta;
        this.rhoMin = rhoMin;
        this.phi = phi;
        this.gamma = gamma;
        this.sigma = sigma;
    }

    public int tenorIndex(String tenor) {
        for (int i = 0; i < TENORS.length; i++) {
            if (TENORS[i].equals(tenor)) return i;
        }
        throw new IllegalArgumentException("Unknown tenor: " + tenor);
    }

    /**
     * Parametric tenor correlation using the standard SIMM formula.
     */
    public double tenorCorrelation(int k, int l) {
        if (k == l) return 1.0;
        double tk = TENOR_YEARS[k];
        double tl = TENOR_YEARS[l];
        return Math.max(
            Math.exp(-theta * Math.abs(tk - tl) / Math.min(tk, tl)),
            rhoMin
        );
    }

    public String getGroup(String currency) {
        return currencyGroups.getOrDefault(currency, "HighVol");
    }

    /**
     * Computes the curvature value-at-risk for a single sensitivity.
     * Uses the delta risk weight and sigma scaling parameter.
     */
    public double computeCVR(double vega, double riskWeight) {
        double shift = sigma * riskWeight * 0.001;
        return vega * (Math.exp(shift) - Math.exp(-shift));
    }

    /**
     * Computes the ISDA SIMM v2.6 IR Curvature Margin.
     *
     * @param curvatureSensitivities list of curvature (vega) sensitivities
     * @return map with "buckets" (per-currency K, sumCVR, lambda, margin)
     *         and "curvatureMargin"
     */
    public Map<String, Object> computeCurvatureMargin(List<Sensitivity> curvatureSensitivities) {
        if (curvatureSensitivities.isEmpty()) {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("buckets", new LinkedHashMap<>());
            result.put("curvatureMargin", 0.0);
            return result;
        }

        // Group by currency bucket
        Map<String, List<Sensitivity>> buckets = new LinkedHashMap<>();
        for (Sensitivity s : curvatureSensitivities) {
            buckets.computeIfAbsent(s.currency, k -> new ArrayList<>()).add(s);
        }

        Map<String, Map<String, Double>> bucketResults = new LinkedHashMap<>();

        for (Map.Entry<String, List<Sensitivity>> entry : buckets.entrySet()) {
            String ccy = entry.getKey();
            List<Sensitivity> sensList = entry.getValue();
            String group = getGroup(ccy);
            double[] rw = riskWeights.get(group);

            int n = sensList.size();
            double[] cvr = new double[n];
            int[] tenorIdx = new int[n];
            String[] subCurves = new String[n];

            for (int i = 0; i < n; i++) {
                tenorIdx[i] = tenorIndex(sensList.get(i).tenor);
                subCurves[i] = sensList.get(i).subCurve;
                cvr[i] = computeCVR(sensList.get(i).value, rw[tenorIdx[i]]);
            }

            // TODO: Implement per-bucket curvature aggregation.
            // Must compute sumCVR, lambda, intra-bucket K, and bucket margin.
            // See ir_curvature_spec.txt for methodology details.
            double sumCVR = 0;
            double lambda = 0;
            double K = 0;
            double margin = 0;

            Map<String, Double> bucketResult = new LinkedHashMap<>();
            bucketResult.put("K", K);
            bucketResult.put("sumCVR", sumCVR);
            bucketResult.put("lambda", lambda);
            bucketResult.put("margin", margin);
            bucketResults.put(ccy, bucketResult);
        }

        // TODO: Implement inter-bucket curvature aggregation.
        // See ir_curvature_spec.txt for methodology details.
        double curvatureMargin = 0.0;

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("buckets", bucketResults);
        result.put("curvatureMargin", curvatureMargin);
        return result;
    }
}
