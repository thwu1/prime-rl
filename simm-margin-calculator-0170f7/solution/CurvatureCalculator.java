import java.util.*;

/**
 * ISDA SIMM v2.6 Interest Rate Curvature Margin Calculator (corrected).
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

    public double computeCVR(double vega, double riskWeight) {
        double shift = sigma * riskWeight * 0.01;
        return vega * (Math.exp(shift) + Math.exp(-shift) - 2.0) / 2.0;
    }

    public Map<String, Object> computeCurvatureMargin(List<Sensitivity> curvatureSensitivities) {
        if (curvatureSensitivities.isEmpty()) {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("buckets", new LinkedHashMap<>());
            result.put("curvatureMargin", 0.0);
            return result;
        }

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

            double sumCVR = 0;
            double sumAbsCVR = 0;
            for (double c : cvr) {
                sumCVR += c;
                sumAbsCVR += Math.abs(c);
            }
            double lambda = sumAbsCVR > 0 ? sumCVR / sumAbsCVR : 0.0;

            double kSquared = 0;
            for (int i = 0; i < n; i++) {
                for (int j = 0; j < n; j++) {
                    double rho = tenorCorrelation(tenorIdx[i], tenorIdx[j]);
                    double rhoSq = rho * rho;
                    double phiFactor = subCurves[i].equals(subCurves[j]) ? 1.0 : phi;
                    kSquared += rhoSq * phiFactor * cvr[i] * cvr[j];
                }
            }
            double K = Math.sqrt(Math.max(0, kSquared));

            double margin = Math.max(sumCVR + lambda * K, 0.0);

            Map<String, Double> bucketResult = new LinkedHashMap<>();
            bucketResult.put("K", K);
            bucketResult.put("sumCVR", sumCVR);
            bucketResult.put("lambda", lambda);
            bucketResult.put("margin", margin);
            bucketResults.put(ccy, bucketResult);
        }

        List<String> ccys = new ArrayList<>(bucketResults.keySet());
        Collections.sort(ccys);

        double curvatureMargin;
        if (ccys.size() == 1) {
            curvatureMargin = bucketResults.get(ccys.get(0)).get("margin");
        } else {
            double total = 0;
            for (String ccy : ccys) {
                double m = bucketResults.get(ccy).get("margin");
                total += m * m;
            }
            for (int i = 0; i < ccys.size(); i++) {
                for (int j = i + 1; j < ccys.size(); j++) {
                    double mi = bucketResults.get(ccys.get(i)).get("margin");
                    double mj = bucketResults.get(ccys.get(j)).get("margin");
                    double si = mi > 0
                        ? Math.max(-mi, Math.min(bucketResults.get(ccys.get(i)).get("sumCVR"), mi))
                        : 0.0;
                    double sj = mj > 0
                        ? Math.max(-mj, Math.min(bucketResults.get(ccys.get(j)).get("sumCVR"), mj))
                        : 0.0;
                    total += 2 * gamma * gamma * si * sj;
                }
            }
            curvatureMargin = Math.sqrt(Math.max(0, total));
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("buckets", bucketResults);
        result.put("curvatureMargin", curvatureMargin);
        return result;
    }
}
