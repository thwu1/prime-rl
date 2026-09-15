package calibrator;


/**
 * Prices calibration instruments in the EUR multicurve framework.
 * All EUR cash flows discounted with OIS curve (multicurve).
 */
public class Pricer {
    private Curve discountCurve;
    private Curve euribor6mCurve;
    private Curve euribor3mCurve;

    public void setDiscountCurve(Curve c) { discountCurve = c; }
    public void setEuribor6mCurve(Curve c) { euribor6mCurve = c; }
    public void setEuribor3mCurve(Curve c) { euribor3mCurve = c; }

    public Curve getDiscountCurve() { return discountCurve; }
    public Curve getEuribor6mCurve() { return euribor6mCurve; }
    public Curve getEuribor3mCurve() { return euribor3mCurve; }

    public double oisSwapPv(double tenor, double fixedRate) {
        double floatPv = 1.0 - discountCurve.discountFactor(tenor);
        double fixedPv = 0.0;
        if (tenor <= 1.0 + 1e-9) {
            fixedPv = fixedRate * tenor * discountCurve.discountFactor(tenor);
        } else {
            int years = (int) Math.round(tenor);
            for (int y = 1; y <= years; y++) {
                fixedPv += fixedRate * 1.0
                    * discountCurve.discountFactor((double) y);
            }
        }
        return floatPv - fixedPv;
    }

    /**
     * FIX: IRS swap discounts all cash flows with OIS curve (not forward curve).
     */
    public double irsSwapPv(double tenor, double fixedRate) {
        double floatPv = 0.0;
        int nFloatPeriods = (int) Math.round(tenor * 2);
        for (int i = 0; i < nFloatPeriods; i++) {
            double t1 = i * 0.5;
            double t2 = (i + 1) * 0.5;
            double fwd = euribor6mCurve.forwardRate(t1, t2);
            floatPv += fwd * 0.5 * discountCurve.discountFactor(t2);
        }

        double fixedPv = 0.0;
        int nFixedPeriods = (int) Math.round(tenor);
        for (int y = 1; y <= nFixedPeriods; y++) {
            fixedPv += fixedRate * 1.0
                * discountCurve.discountFactor((double) y);
        }

        return floatPv - fixedPv;
    }

    /**
     * FIX: Basis swap spread is ADDED to the 3M leg (not subtracted).
     */
    public double basisSwapPv(double tenor, double spread) {
        double leg3mPv = 0.0;
        int n3mPeriods = (int) Math.round(tenor * 4);
        for (int i = 0; i < n3mPeriods; i++) {
            double t1 = i * 0.25;
            double t2 = (i + 1) * 0.25;
            double fwd3m = euribor3mCurve.forwardRate(t1, t2);
            leg3mPv += (fwd3m + spread) * 0.25
                * discountCurve.discountFactor(t2);
        }

        double leg6mPv = 0.0;
        int n6mPeriods = (int) Math.round(tenor * 2);
        for (int i = 0; i < n6mPeriods; i++) {
            double t1 = i * 0.5;
            double t2 = (i + 1) * 0.5;
            double fwd6m = euribor6mCurve.forwardRate(t1, t2);
            leg6mPv += fwd6m * 0.5
                * discountCurve.discountFactor(t2);
        }

        return leg3mPv - leg6mPv;
    }

    public double fraPv(double startTime, double endTime,
                        double fraRate, Curve forwardCurve) {
        double fwd = forwardCurve.forwardRate(startTime, endTime);
        double tau = endTime - startTime;
        double df = discountCurve.discountFactor(endTime);
        return (fwd - fraRate) * tau * df / (1.0 + fwd * tau);
    }

    public double fixingPv(double tenor, double fixingRate,
                           Curve forwardCurve) {
        double fwd = forwardCurve.forwardRate(0.0, tenor);
        double df = discountCurve.discountFactor(tenor);
        return (fwd - fixingRate) * tenor * df;
    }
}
