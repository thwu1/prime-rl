
/**
 * Prices calibration instruments in the EUR multicurve framework.
 *
 * Three curves are used:
 *   - discountCurve:   OIS discount / EONIA forward
 *   - euribor6mCurve:  EURIBOR 6M forward
 *   - euribor3mCurve:  EURIBOR 3M forward
 */
public class Pricer {
    private Curve discountCurve;
    private Curve euribor6mCurve;
    private Curve euribor3mCurve;

    public void setDiscountCurve(Curve c) { discountCurve = c; }
    public void setEuribor6mCurve(Curve c) { euribor6mCurve = c; }
    public void setEuribor3mCurve(Curve c) { euribor3mCurve = c; }

    /**
     * PV of an OIS swap (fixed annual vs EONIA compounded overnight).
     * Float leg PV = 1 - DF_OIS(T), since EONIA is the OIS discount rate.
     * Fixed leg PV = K * sum(yearFrac_i * DF_OIS(t_i)).
     */
    public double oisSwapPv(double tenor, double fixedRate) {
        double floatPv = 1.0 - discountCurve.discountFactor(tenor);
        double fixedPv = 0.0;
        if (tenor <= 1.0 + 1e-9) {
            // Single payment at maturity for sub-annual swaps
            fixedPv = fixedRate * tenor * discountCurve.discountFactor(tenor);
        } else {
            // Annual fixed payments
            int years = (int) Math.round(tenor);
            for (int y = 1; y <= years; y++) {
                fixedPv += fixedRate * 1.0 * discountCurve.discountFactor((double) y);
            }
        }
        return floatPv - fixedPv;
    }

    /**
     * PV of an IRS swap (fixed annual vs EURIBOR 6M semi-annual).
     * In the multicurve framework, forward rates are projected from the
     * EURIBOR 6M curve and all cash flows are discounted with the OIS curve.
     */
    public double irsSwapPv(double tenor, double fixedRate) {
        // Float leg: semi-annual EURIBOR 6M coupons
        double floatPv = 0.0;
        int nFloatPeriods = (int) Math.round(tenor * 2);
        for (int i = 0; i < nFloatPeriods; i++) {
            double t1 = i * 0.5;
            double t2 = (i + 1) * 0.5;
            double fwd = euribor6mCurve.forwardRate(t1, t2);
            floatPv += fwd * 0.5 * euribor6mCurve.discountFactor(t2);
        }

        // Fixed leg: annual fixed coupons
        double fixedPv = 0.0;
        int nFixedPeriods = (int) Math.round(tenor);
        for (int y = 1; y <= nFixedPeriods; y++) {
            fixedPv += fixedRate * 1.0 * euribor6mCurve.discountFactor((double) y);
        }

        return floatPv - fixedPv;
    }

    /**
     * PV of a basis swap (EURIBOR 3M + spread quarterly vs EURIBOR 6M semi-annual).
     * Both legs discounted with OIS discount curve.
     * Market quote = spread on the 3M leg.
     */
    public double basisSwapPv(double tenor, double spread) {
        // 3M leg: quarterly payments of (EURIBOR 3M forward + spread)
        double leg3mPv = 0.0;
        int n3mPeriods = (int) Math.round(tenor * 4);
        for (int i = 0; i < n3mPeriods; i++) {
            double t1 = i * 0.25;
            double t2 = (i + 1) * 0.25;
            double fwd3m = euribor3mCurve.forwardRate(t1, t2);
            leg3mPv += (fwd3m - spread) * 0.25 * discountCurve.discountFactor(t2);
        }

        // 6M leg: semi-annual payments of EURIBOR 6M forward
        double leg6mPv = 0.0;
        int n6mPeriods = (int) Math.round(tenor * 2);
        for (int i = 0; i < n6mPeriods; i++) {
            double t1 = i * 0.5;
            double t2 = (i + 1) * 0.5;
            double fwd6m = euribor6mCurve.forwardRate(t1, t2);
            leg6mPv += fwd6m * 0.5 * discountCurve.discountFactor(t2);
        }

        return leg3mPv - leg6mPv;
    }

    /**
     * PV of a FRA (Forward Rate Agreement).
     * PV = (fwd - K) * tau * DF / (1 + fwd * tau)
     */
    public double fraPv(double startTime, double endTime,
                        double fraRate, Curve forwardCurve) {
        double fwd = forwardCurve.forwardRate(startTime, endTime);
        double tau = endTime - startTime;
        double df = discountCurve.discountFactor(endTime);
        return (fwd - fraRate) * tau * df / (1.0 + fwd * tau);
    }

    /**
     * PV of an Ibor fixing deposit (current-period fixing check).
     * forward(0, tenor) should match the fixing rate.
     */
    public double fixingPv(double tenor, double fixingRate,
                           Curve forwardCurve) {
        double fwd = forwardCurve.forwardRate(0.0, tenor);
        double df = discountCurve.discountFactor(tenor);
        return (fwd - fixingRate) * tenor * df;
    }
}
