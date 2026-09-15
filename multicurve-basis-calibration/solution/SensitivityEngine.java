package calibrator;


import java.util.*;

/**
 * Bucketed PV01 computation for portfolio positions against calibrated curves.
 * PV01 for node j = PV(r_j + 1bp) - PV(r_j), no re-calibration after bumping.
 */
public class SensitivityEngine {

    private final Pricer pricer;
    private static final double BUMP_SIZE = 0.0001; // 1 basis point

    public SensitivityEngine(Pricer pricer) {
        this.pricer = pricer;
    }

    public Map<String, double[]> computePV01(String type, double tenor,
                                              double rate, double notional) {
        Map<String, double[]> result = new LinkedHashMap<>();

        Curve[] curves = {
            pricer.getDiscountCurve(),
            pricer.getEuribor6mCurve(),
            pricer.getEuribor3mCurve()
        };
        String[] names = {
            "EUR-DSCON-OIS",
            "EUR-EURIBOR6M-IRS",
            "EUR-EURIBOR3M-BS"
        };

        double basePv = notional * priceSwap(type, tenor, rate);

        for (int c = 0; c < curves.length; c++) {
            Curve curve = curves[c];
            double[] pv01 = new double[curve.getNodeCount()];
            for (int j = 0; j < curve.getNodeCount(); j++) {
                double orig = curve.getZeroRate(j);
                curve.setZeroRate(j, orig + BUMP_SIZE);
                double bumpedPv = notional * priceSwap(type, tenor, rate);
                pv01[j] = bumpedPv - basePv;
                curve.setZeroRate(j, orig);
            }
            result.put(names[c], pv01);
        }

        return result;
    }

    private double priceSwap(String type, double tenor, double rate) {
        switch (type) {
            case "OIS":    return pricer.oisSwapPv(tenor, rate);
            case "IRS6M":  return pricer.irsSwapPv(tenor, rate);
            case "BS3M6M": return pricer.basisSwapPv(tenor, rate);
            default: throw new IllegalArgumentException("Unknown: " + type);
        }
    }
}
