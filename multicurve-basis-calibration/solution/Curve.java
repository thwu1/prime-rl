package calibrator;


/**
 * Interpolated zero-rate curve for interest rate modeling.
 * Uses log-linear DF interpolation: ln(DF(t)) is piecewise-linear in t.
 */
public class Curve {
    private final String name;
    private final double[] nodeTimes;
    private double[] zeroRates;

    public Curve(String name, double[] nodeTimes) {
        this.name = name;
        this.nodeTimes = nodeTimes.clone();
        this.zeroRates = new double[nodeTimes.length];
    }

    public String getName() { return name; }
    public int getNodeCount() { return nodeTimes.length; }
    public double getNodeTime(int i) { return nodeTimes[i]; }
    public double getZeroRate(int i) { return zeroRates[i]; }
    public void setZeroRate(int i, double rate) { zeroRates[i] = rate; }
    public double[] getParameters() { return zeroRates.clone(); }

    public void setParameters(double[] params) {
        System.arraycopy(params, 0, zeroRates, 0, params.length);
    }

    /**
     * Compute the discount factor at time t.
     * Log-linear DF interpolation: linear interpolation on r(t)*t.
     */
    public double discountFactor(double t) {
        if (t <= 0.0) return 1.0;

        if (t <= nodeTimes[0]) {
            return Math.exp(-zeroRates[0] * t);
        }
        if (t >= nodeTimes[nodeTimes.length - 1]) {
            return Math.exp(-zeroRates[nodeTimes.length - 1] * t);
        }

        int idx = 0;
        while (idx < nodeTimes.length - 1 && nodeTimes[idx + 1] < t) {
            idx++;
        }

        double t1 = nodeTimes[idx];
        double t2 = nodeTimes[idx + 1];
        double r1 = zeroRates[idx];
        double r2 = zeroRates[idx + 1];
        double w = (t - t1) / (t2 - t1);

        // FIX: Log-linear on DF = linear interpolation on r*t
        double rt = r1 * t1 + (r2 * t2 - r1 * t1) * w;
        return Math.exp(-rt);
    }

    public double forwardRate(double t1, double t2) {
        if (t2 <= t1) {
            throw new IllegalArgumentException(
                "t2 must be > t1: " + t1 + " >= " + t2);
        }
        double df1 = discountFactor(t1);
        double df2 = discountFactor(t2);
        return (df1 / df2 - 1.0) / (t2 - t1);
    }
}
