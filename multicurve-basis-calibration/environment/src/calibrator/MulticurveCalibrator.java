package calibrator;


import java.io.*;
import java.util.*;

/**
 * EUR Multicurve Calibrator
 *
 * Calibrates three EUR interest rate curves from market data:
 *   1. EUR-DSCON-OIS      - OIS discount + EONIA forward
 *   2. EUR-EURIBOR6M-IRS  - EURIBOR 6M forward
 *   3. EUR-EURIBOR3M-BS   - EURIBOR 3M forward
 *
 * Then prices a portfolio and computes bucketed PV01.
 * Output: /app/results.json
 */
public class MulticurveCalibrator {

    private final Map<String, Double> quotes = new LinkedHashMap<>();
    private final List<String[]> portfolio = new ArrayList<>();
    private Curve discountCurve;
    private Curve euribor6mCurve;
    private Curve euribor3mCurve;
    private final Pricer pricer = new Pricer();

    // Node times (year fractions)
    private static final double[] OIS_TIMES = {
        1.0/12, 2.0/12, 3.0/12, 6.0/12,
        1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0
    };
    private static final String[] OIS_LABELS = {
        "1M","2M","3M","6M",
        "1Y","2Y","3Y","4Y","5Y","7Y","10Y","15Y","20Y","30Y"
    };
    private static final double[] IRS_TIMES = {
        0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0
    };
    private static final double[] BS_TIMES = {
        0.25, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0
    };

    public static void main(String[] args) {
        try {
            MulticurveCalibrator cal = new MulticurveCalibrator();
            cal.loadMarketData("/app/data/market_quotes.csv");
            cal.loadPortfolio("/app/data/portfolio.csv");
            cal.initCurves();
            cal.calibrate();
            cal.writeResults("/app/results.json");
            System.out.println("\nResults written to /app/results.json");
        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }
    }

    private void loadMarketData(String path) throws IOException {
        try (BufferedReader br = new BufferedReader(new FileReader(path))) {
            br.readLine(); // skip header
            String line;
            while ((line = br.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty()) continue;
                String[] parts = line.split(",");
                quotes.put(parts[0] + ":" + parts[1],
                           Double.parseDouble(parts[2]));
            }
        }
        System.out.println("Loaded " + quotes.size() + " market quotes");
    }

    private void loadPortfolio(String path) throws IOException {
        try (BufferedReader br = new BufferedReader(new FileReader(path))) {
            br.readLine(); // skip header
            String line;
            while ((line = br.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty()) continue;
                portfolio.add(line.split(","));
            }
        }
        System.out.println("Loaded " + portfolio.size() + " portfolio positions");
    }

    private void initCurves() {
        discountCurve   = new Curve("EUR-DSCON-OIS", OIS_TIMES);
        euribor6mCurve  = new Curve("EUR-EURIBOR6M-IRS", IRS_TIMES);
        euribor3mCurve  = new Curve("EUR-EURIBOR3M-BS", BS_TIMES);
        pricer.setDiscountCurve(discountCurve);
        pricer.setEuribor6mCurve(euribor6mCurve);
        pricer.setEuribor3mCurve(euribor3mCurve);
    }

    private void calibrate() {
        System.out.println("\n=== EUR 3-Curve Multicurve Calibration ===");
        System.out.println("Valuation date: 2015-11-20\n");
        calibrateOis();
        calibrateBs();
        calibrateIrs();
        System.out.println("\nCalibration complete.");
    }

    // --- Step 1: OIS discount curve ---
    private void calibrateOis() {
        System.out.println("Calibrating EUR-DSCON-OIS ...");
        int n = OIS_TIMES.length;
        double[] mkt = new double[n];
        double[] guess = new double[n];
        for (int i = 0; i < n; i++) {
            mkt[i] = quotes.get("OIS:" + OIS_LABELS[i]);
            guess[i] = mkt[i];
        }
        double[] result = NewtonSolver.solve(n, params -> {
            discountCurve.setParameters(params);
            double[] pvs = new double[n];
            for (int i = 0; i < n; i++)
                pvs[i] = pricer.oisSwapPv(OIS_TIMES[i], mkt[i]);
            return pvs;
        }, guess);
        discountCurve.setParameters(result);
    }

    // --- Step 2: EURIBOR 6M forward curve ---
    private void calibrateIrs() {
        System.out.println("Calibrating EUR-EURIBOR6M-IRS ...");
        int n = IRS_TIMES.length;
        double[] mkt = new double[n];
        double[] guess = new double[n];

        mkt[0] = quotes.get("FIX6M:0D");
        mkt[1] = quotes.get("FRA6M:6Mx12M");
        String[] tenors = {"2Y","3Y","4Y","5Y","7Y","10Y","15Y","20Y","30Y"};
        for (int i = 0; i < tenors.length; i++)
            mkt[i + 2] = quotes.get("IRS6M:" + tenors[i]);
        for (int i = 0; i < n; i++) guess[i] = mkt[i];

        double[] tv = {2,3,4,5,7,10,15,20,30};

        double[] result = NewtonSolver.solve(n, params -> {
            euribor6mCurve.setParameters(params);
            double[] pvs = new double[n];
            pvs[0] = pricer.fixingPv(0.5, mkt[0], euribor6mCurve);
            pvs[1] = pricer.fraPv(0.5, 1.0, mkt[1], euribor6mCurve);
            for (int i = 0; i < tv.length; i++)
                pvs[i+2] = pricer.irsSwapPv(tv[i], mkt[i+2]);
            return pvs;
        }, guess);
        euribor6mCurve.setParameters(result);
    }

    // --- Step 3: EURIBOR 3M forward curve ---
    private void calibrateBs() {
        System.out.println("Calibrating EUR-EURIBOR3M-BS ...");
        int n = BS_TIMES.length;
        double[] mkt = new double[n];
        double[] guess = new double[n];

        mkt[0] = quotes.get("FIX3M:0D");
        mkt[1] = quotes.get("FRA3M:3Mx6M");
        String[] tenors = {"1Y","2Y","3Y","4Y","5Y","7Y","10Y","15Y","20Y","30Y"};
        for (int i = 0; i < tenors.length; i++)
            mkt[i + 2] = quotes.get("BS3M6M:" + tenors[i]);

        for (int i = 0; i < n; i++) {
            int idx = Math.min(i, euribor6mCurve.getNodeCount() - 1);
            guess[i] = euribor6mCurve.getZeroRate(idx);
        }

        double[] tv = {1,2,3,4,5,7,10,15,20,30};

        double[] result = NewtonSolver.solve(n, params -> {
            euribor3mCurve.setParameters(params);
            double[] pvs = new double[n];
            pvs[0] = pricer.fixingPv(0.25, mkt[0], euribor3mCurve);
            pvs[1] = pricer.fraPv(0.25, 0.5, mkt[1], euribor3mCurve);
            for (int i = 0; i < tv.length; i++)
                pvs[i+2] = pricer.basisSwapPv(tv[i], mkt[i+2]);
            return pvs;
        }, guess);
        euribor3mCurve.setParameters(result);
    }

    private double priceSwap(String type, double tenor, double rate) {
        switch (type) {
            case "OIS":    return pricer.oisSwapPv(tenor, rate);
            case "IRS6M":  return pricer.irsSwapPv(tenor, rate);
            case "BS3M6M": return pricer.basisSwapPv(tenor, rate);
            default: throw new IllegalArgumentException("Unknown type: " + type);
        }
    }

    // ---------------------------------------------------------------
    private void writeResults(String path) throws IOException {
        SensitivityEngine sens = new SensitivityEngine(pricer);

        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("{");
            pw.println("  \"valuation_date\": \"2015-11-20\",");

            // Curves
            pw.println("  \"curves\": {");
            writeCurve(pw, discountCurve);   pw.println(",");
            writeCurve(pw, euribor6mCurve);  pw.println(",");
            writeCurve(pw, euribor3mCurve);  pw.println();
            pw.println("  },");

            // Instrument PVs
            pw.println("  \"instrument_pvs\": {");
            List<String> pvEntries = new ArrayList<>();
            for (int i = 0; i < OIS_TIMES.length; i++)
                pvEntries.add(fmtEntry("OIS-" + OIS_LABELS[i],
                    pricer.oisSwapPv(OIS_TIMES[i],
                        quotes.get("OIS:" + OIS_LABELS[i]))));
            pvEntries.add(fmtEntry("FIX-6M",
                pricer.fixingPv(0.5, quotes.get("FIX6M:0D"),
                    euribor6mCurve)));
            pvEntries.add(fmtEntry("FRA-6Mx12M",
                pricer.fraPv(0.5, 1.0, quotes.get("FRA6M:6Mx12M"),
                    euribor6mCurve)));
            String[] irsT = {"2Y","3Y","4Y","5Y","7Y","10Y","15Y","20Y","30Y"};
            double[] irsV = {2,3,4,5,7,10,15,20,30};
            for (int i = 0; i < irsT.length; i++)
                pvEntries.add(fmtEntry("IRS6M-" + irsT[i],
                    pricer.irsSwapPv(irsV[i],
                        quotes.get("IRS6M:" + irsT[i]))));
            pvEntries.add(fmtEntry("FIX-3M",
                pricer.fixingPv(0.25, quotes.get("FIX3M:0D"),
                    euribor3mCurve)));
            pvEntries.add(fmtEntry("FRA-3Mx6M",
                pricer.fraPv(0.25, 0.5, quotes.get("FRA3M:3Mx6M"),
                    euribor3mCurve)));
            String[] bsT = {"1Y","2Y","3Y","4Y","5Y","7Y","10Y","15Y","20Y","30Y"};
            double[] bsV = {1,2,3,4,5,7,10,15,20,30};
            for (int i = 0; i < bsT.length; i++)
                pvEntries.add(fmtEntry("BS3M6M-" + bsT[i],
                    pricer.basisSwapPv(bsV[i],
                        quotes.get("BS3M6M:" + bsT[i]))));
            for (int i = 0; i < pvEntries.size(); i++) {
                pw.print(pvEntries.get(i));
                pw.println(i < pvEntries.size() - 1 ? "," : "");
            }
            pw.println("  },");

            // Portfolio
            pw.println("  \"portfolio\": {");
            for (int p = 0; p < portfolio.size(); p++) {
                String[] pos = portfolio.get(p);
                String id = pos[0];
                String type = pos[1];
                double tenor = Double.parseDouble(pos[2]);
                double rate = Double.parseDouble(pos[3]);
                double notional = Double.parseDouble(pos[4]);

                double unitPv = priceSwap(type, tenor, rate);
                double pv = notional * unitPv;

                Map<String, double[]> pv01 =
                    sens.computePV01(type, tenor, rate, notional);

                pw.println("    \"" + id + "\": {");
                pw.printf("      \"pv\": %.10e,%n", pv);
                pw.println("      \"pv01\": {");

                String[] curveNames = {
                    "EUR-DSCON-OIS",
                    "EUR-EURIBOR6M-IRS",
                    "EUR-EURIBOR3M-BS"
                };
                for (int c = 0; c < curveNames.length; c++) {
                    double[] sensArr = pv01.get(curveNames[c]);
                    pw.print("        \"" + curveNames[c] + "\": [");
                    for (int j = 0; j < sensArr.length; j++) {
                        if (j > 0) pw.print(", ");
                        pw.printf("%.10e", sensArr[j]);
                    }
                    pw.println("]"
                        + (c < curveNames.length - 1 ? "," : ""));
                }
                pw.println("      }");
                pw.println("    }"
                    + (p < portfolio.size() - 1 ? "," : ""));
            }
            pw.println("  }");
            pw.println("}");
        }
    }

    private static String fmtEntry(String label, double pv) {
        return String.format("    \"%s\": %.15e", label, pv);
    }

    private static void writeCurve(PrintWriter pw, Curve c) {
        pw.println("    \"" + c.getName() + "\": {");
        pw.print("      \"times\": [");
        for (int i = 0; i < c.getNodeCount(); i++) {
            if (i > 0) pw.print(", ");
            pw.printf("%.10f", c.getNodeTime(i));
        }
        pw.println("],");
        pw.print("      \"zero_rates\": [");
        for (int i = 0; i < c.getNodeCount(); i++) {
            if (i > 0) pw.print(", ");
            pw.printf("%.15f", c.getZeroRate(i));
        }
        pw.println("],");
        pw.print("      \"discount_factors\": [");
        for (int i = 0; i < c.getNodeCount(); i++) {
            if (i > 0) pw.print(", ");
            pw.printf("%.15f", c.discountFactor(c.getNodeTime(i)));
        }
        pw.println("]");
        pw.print("    }");
    }
}
