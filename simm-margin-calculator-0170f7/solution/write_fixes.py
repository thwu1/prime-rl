#!/usr/bin/env python3
"""
Writes corrected DeltaCalculator.java, CurvatureCalculator.java,
and RiskAggregator.java to /app/src/.

"""

DELTA_CALC = r'''import java.util.*;

/**
 * ISDA SIMM v2.6 Interest Rate Delta Margin Calculator (corrected).
 *
 */
public class DeltaCalculator {

    public static final String[] TENORS = {
        "2W", "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "15Y", "20Y", "30Y"
    };

    public static final double[] TENOR_YEARS = {
        2.0 / 52.0, 1.0 / 12.0, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0,
        10.0, 15.0, 20.0, 30.0
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
        // FIX: use min(tk, tl) not max(tk, tl)
        return Math.max(
            Math.exp(-theta * Math.abs(tk - tl) / Math.min(tk, tl)),
            rhoMin
        );
    }

    public String getGroup(String currency) {
        return currencyGroups.getOrDefault(currency, "HighVol");
    }

    public Map<String, Object> computeDeltaMargin(List<Sensitivity> portfolio) {
        if (portfolio.isEmpty()) {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("buckets", new LinkedHashMap<>());
            result.put("deltaMargin", 0.0);
            return result;
        }

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

            double netSens = 0;
            for (Sensitivity s : sensList) {
                netSens += s.value;
            }
            // FIX: CR = max(1, sqrt(|net|/threshold)) not max(1, |net|/threshold)
            double cr = Math.max(1.0, Math.sqrt(Math.abs(netSens) / threshold));

            int n = sensList.size();
            double[] ws = new double[n];
            int[] tenorIdx = new int[n];
            String[] subCurves = new String[n];
            for (int i = 0; i < n; i++) {
                tenorIdx[i] = tenorIndex(sensList.get(i).tenor);
                subCurves[i] = sensList.get(i).subCurve;
                ws[i] = rw[tenorIdx[i]] * sensList.get(i).value * cr;
            }

            double kSquared = 0;
            for (int i = 0; i < n; i++) {
                for (int j = 0; j < n; j++) {
                    double rho = tenorCorrelation(tenorIdx[i], tenorIdx[j]);
                    // FIX: use phi when subcurves differ, not hardcoded 1.0
                    double phiFactor = subCurves[i].equals(subCurves[j]) ? 1.0 : phi;
                    kSquared += rho * phiFactor * ws[i] * ws[j];
                }
            }
            double K = Math.sqrt(Math.max(0, kSquared));

            double S = 0;
            for (double w : ws) S += w;

            Map<String, Double> result = new LinkedHashMap<>();
            result.put("K", K);
            result.put("S", S);
            result.put("CR", cr);
            bucketResults.put(ccy, result);
        }

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
'''

CURVATURE_CALC = r'''import java.util.*;

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

    // FIX: correct shift scale (0.01 not 0.001) and formula (cosh-1 not sinh)
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

            // Per-bucket aggregation
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

        // Inter-bucket aggregation
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
'''

RISK_AGGREGATOR = r'''/**
 * Combines delta and curvature margins into total IR margin (corrected).
 *
 */
public class RiskAggregator {

    private final double rhoDeltaCurvature;

    public RiskAggregator(double rhoDeltaCurvature) {
        this.rhoDeltaCurvature = rhoDeltaCurvature;
    }

    // FIX: use correlated sqrt formula instead of simple addition
    public double computeTotalMargin(double deltaMargin, double curvatureMargin) {
        return Math.sqrt(
            deltaMargin * deltaMargin
            + curvatureMargin * curvatureMargin
            + 2 * rhoDeltaCurvature * deltaMargin * curvatureMargin
        );
    }
}
'''

with open('/app/src/DeltaCalculator.java', 'w') as f:
    f.write(DELTA_CALC)

with open('/app/src/CurvatureCalculator.java', 'w') as f:
    f.write(CURVATURE_CALC)

with open('/app/src/RiskAggregator.java', 'w') as f:
    f.write(RISK_AGGREGATOR)

print("Corrected Java files written successfully.")
