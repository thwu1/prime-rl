import java.util.*;

/**
 * Hull-White one-factor short rate model pricing engine.
 *
 */
public class HullWhiteEngine {

    // ---- model config ----
    static double a;          // mean reversion
    static double sigma;      // short rate volatility
    static double[] zrTenors; // zero rate tenors
    static double[] zrRates;  // zero rates (continuously compounded)
    static int numPaths;
    static long seed;
    static double dt;         // MC time step
    static double horizon;    // MC horizon

    static double[] bondMats;
    static double[] capletMats;
    static double capletTenor;
    static double capletStrikeOffset;
    static double bermFirst, bermLast, bermEnd, bermPeriod;

    // ---- entry point ----

    public static void main(String[] args) throws Exception {
        readConfig("/app/config.json");

        Map<String, Object> out = new LinkedHashMap<>();

        // Discount factors
        double[] dfs = new double[bondMats.length];
        for (int i = 0; i < bondMats.length; i++) dfs[i] = df(bondMats[i]);
        out.put("discount_factors", dfs);

        // B values
        out.put("B_values", new double[]{B(0,1), B(0,5), B(0,10), B(0,20)});

        // Conditional variance
        out.put("conditional_variance", new double[]{condVar(0,1), condVar(0,5), condVar(0,10)});

        // Forward bond vol
        double[] fbv = new double[capletMats.length];
        for (int i = 0; i < capletMats.length; i++) {
            double T = capletMats[i];
            double phi = condVar(0, T);
            double bVal = B(T, T + capletTenor);
            fbv[i] = Math.sqrt(phi * bVal * bVal / T);
        }
        out.put("forward_bond_volatility", fbv);

        // MC simulation
        runMonteCarlo(out);

        SimpleJson.writeFile("/app/results.json", out);
    }

    // ---- discount curve ----

    static double zeroRate(double t) {
        if (t <= zrTenors[0]) return zrRates[0];
        if (t >= zrTenors[zrTenors.length - 1]) return zrRates[zrRates.length - 1];
        for (int i = 0; i < zrTenors.length - 1; i++) {
            if (t <= zrTenors[i + 1]) {
                double w = (t - zrTenors[i]) / (zrTenors[i + 1] - zrTenors[i]);
                return zrRates[i] + w * (zrRates[i + 1] - zrRates[i]);
            }
        }
        return zrRates[zrRates.length - 1];
    }

    static double df(double t) {
        if (t <= 0) return 1.0;
        return Math.exp(-zeroRate(t) * t);
    }

    /** Compute the model's forward rate at time t. */
    static double instForward(double t) {
        if (t < zrTenors[0]) return zrRates[0];
        if (t > zrTenors[zrTenors.length - 1]) return zrRates[zrRates.length - 1];
        for (int i = 0; i < zrTenors.length - 1; i++) {
            if (t <= zrTenors[i + 1]) {
                double slope = (zrRates[i + 1] - zrRates[i]) / (zrTenors[i + 1] - zrTenors[i]);
                return zrRates[i] + slope * (t - zrTenors[i]);
            }
        }
        return zrRates[zrRates.length - 1];
    }

    // ---- HW analytic functions ----

    static double B(double t, double T) {
        double tau = T - t;
        if (Math.abs(a * tau) < 1e-14) return tau;
        return (1.0 - Math.exp(-a * tau)) / a;
    }

    static double condVar(double s, double t) {
        return sigma * sigma / (2.0 * a) * (1.0 - Math.exp(-2.0 * a * (t - s)));
    }

    /** Convexity adjustment term. */
    static double phi(double t) {
        double e = 1.0 - Math.exp(-a * t);
        return sigma * sigma / (2.0 * a * a) * e * e;
    }

    /** Log of A(t,T) in the bond formula P(t,T) = A(t,T)*exp(-B(t,T)*r). */
    static double lnA(double t, double T) {
        double bVal = B(t, T);
        double fwd = instForward(t);
        double logDfRatio = Math.log(df(T) / df(t));
        double convex = sigma * sigma / (4.0 * a) * (1.0 - Math.exp(-2.0 * a * t)) * bVal * bVal;
        return logDfRatio + bVal * fwd + convex;
    }

    /** Bond price P(t,T) given short rate r at time t. */
    static double bondPrice(double t, double T, double r) {
        return Math.exp(lnA(t, T) - B(t, T) * r);
    }

    /** Total vol of the forward bond P(T,S). */
    static double totalBondVol(double T, double S) {
        return sigma / a * (1.0 - Math.exp(-a * (S - T)))
                * (1.0 - Math.exp(-2.0 * a * T)) / (2.0 * a);
    }

    /** Analytic zero-coupon bond put: put on P(T,S) with strike X. */
    static double zeroBondPut(double T, double S, double X) {
        double F = df(S) / df(T);
        double sp = totalBondVol(T, S);
        if (sp <= 1e-30) return Math.max(X - F, 0.0) * df(T);
        double d1 = (Math.log(F / X) + 0.5 * sp * sp) / sp;
        double d2 = d1 - sp;
        return X * df(T) * normCDF(-d2) - df(S) * normCDF(-d1);
    }

    // ---- normal distribution ----

    static double normCDF(double x) {
        return 0.5 * (1.0 + erf(x / Math.sqrt(2.0)));
    }

    static double normPDF(double x) {
        return Math.exp(-0.5 * x * x) / Math.sqrt(2.0 * Math.PI);
    }

    static double erf(double x) {
        double ax = Math.abs(x);
        double t = 1.0 / (1.0 + 0.3275911 * ax);
        double poly = t * (0.254829592
                + t * (-0.284496736
                + t * (1.421413741
                + t * (-1.453152027
                + t * 1.061405429))));
        double r = 1.0 - poly * Math.exp(-ax * ax);
        return x >= 0 ? r : -r;
    }

    // ---- implied vol ----

    /** Invert the normal-model pricing formula for implied volatility. */
    static double bachelierImpliedVol(double forward, double strike, double T,
                                      double payoffUnit, double price) {
        // Not yet implemented
        return 0.0;
    }

    // ---- Monte Carlo ----

    static void runMonteCarlo(Map<String, Object> out) {
        int nSteps = (int) (horizon / dt);
        double decay = Math.exp(-a * dt);
        double diffusion = sigma * Math.sqrt(dt);

        double[][] rates = new double[numPaths][nSteps + 1];
        double[][] logBA = new double[numPaths][nSteps + 1];

        Random rng = new Random(seed);

        for (int p = 0; p < numPaths; p++) {
            double x = 0.0;
            double cumR = 0.0;
            for (int i = 0; i <= nSteps; i++) {
                double t = i * dt;
                double r = x + instForward(t) + phi(t);
                rates[p][i] = r;
                logBA[p][i] = cumR;
                if (i < nSteps) {
                    cumR += r * dt;
                    x = x * decay + diffusion * rng.nextGaussian();
                }
            }
        }

        // --- Bond prices ---
        double[] mcBonds = new double[bondMats.length];
        for (int j = 0; j < bondMats.length; j++) {
            int idx = (int) Math.round(bondMats[j] / dt);
            double sum = 0.0;
            for (int p = 0; p < numPaths; p++) sum += Math.exp(-logBA[p][idx]);
            mcBonds[j] = sum / numPaths;
        }
        out.put("mc_bond_prices", mcBonds);

        // --- Caplets ---
        double[] fwds = new double[capletMats.length];
        double[] strikes = new double[capletMats.length];
        double[] mcCapPrices = new double[capletMats.length];
        double[] mcCapIV = new double[capletMats.length];
        double[] anCapIV = new double[capletMats.length];

        for (int j = 0; j < capletMats.length; j++) {
            double T = capletMats[j];
            double delta = capletTenor;
            int idx = (int) Math.round(T / dt);

            double F = (df(T) / df(T + delta) - 1.0) / delta;
            fwds[j] = F;
            double K = F + capletStrikeOffset;
            strikes[j] = K;

            double sum = 0.0;
            for (int p = 0; p < numPaths; p++) {
                double DT = Math.exp(-logBA[p][idx]);
                double rT = rates[p][idx];
                double bond = bondPrice(T, T + delta, rT);
                double payoff = Math.max(1.0 - (1.0 + K * delta) * bond, 0.0);
                sum += DT * payoff;
            }
            mcCapPrices[j] = sum / numPaths;

            double payoffUnit = df(T + delta) * delta;

            mcCapIV[j] = bachelierImpliedVol(F, K, T, payoffUnit, mcCapPrices[j]);

            double X = 1.0 / (1.0 + K * delta);
            double zbp = zeroBondPut(T, T + delta, X);
            double anCapPrice = (1.0 + K * delta) * zbp;
            anCapIV[j] = bachelierImpliedVol(F, K, T, payoffUnit, anCapPrice);
        }

        out.put("caplet_forward_rates", fwds);
        out.put("caplet_strikes", strikes);
        out.put("mc_caplet_prices", mcCapPrices);
        out.put("mc_caplet_implied_normal_vols", mcCapIV);
        out.put("analytic_caplet_implied_normal_vols", anCapIV);

        // --- Swaptions ---
        priceSwaptions(rates, logBA, nSteps, out);
    }

    /** Price European and Bermudan payer swaptions. */
    static void priceSwaptions(double[][] rates, double[][] logBA,
                               int nSteps, Map<String, Object> out) {
        // Not yet implemented
        out.put("european_swaption_value", 0.0);
        out.put("bermudan_swaption_value", 0.0);
    }

    // ---- config reading ----

    static void readConfig(String path) throws Exception {
        Map<String, Object> cfg = SimpleJson.readFile(path);
        a = SimpleJson.getDouble(cfg, "mean_reversion");
        sigma = SimpleJson.getDouble(cfg, "volatility");
        zrTenors = SimpleJson.getDoubleArray(cfg, "zero_rate_tenors");
        zrRates = SimpleJson.getDoubleArray(cfg, "zero_rates");
        numPaths = SimpleJson.getInt(cfg, "num_paths");
        seed = SimpleJson.getLong(cfg, "seed");
        dt = SimpleJson.getDouble(cfg, "time_step");
        horizon = SimpleJson.getDouble(cfg, "horizon");
        bondMats = SimpleJson.getDoubleArray(cfg, "bond_maturities");
        capletMats = SimpleJson.getDoubleArray(cfg, "caplet_maturities");
        capletTenor = SimpleJson.getDouble(cfg, "caplet_tenor");
        capletStrikeOffset = SimpleJson.getDouble(cfg, "caplet_strike_offset");
        bermFirst = SimpleJson.getDouble(cfg, "bermudan_first_exercise");
        bermLast = SimpleJson.getDouble(cfg, "bermudan_last_exercise");
        bermEnd = SimpleJson.getDouble(cfg, "bermudan_swap_end");
        bermPeriod = SimpleJson.getDouble(cfg, "bermudan_period_length");
    }
}
