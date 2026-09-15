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

        // 1. Discount factors
        double[] dfs = new double[bondMats.length];
        for (int i = 0; i < bondMats.length; i++) dfs[i] = df(bondMats[i]);
        out.put("discount_factors", dfs);

        // 2. B values
        out.put("B_values", new double[]{B(0,1), B(0,5), B(0,10), B(0,20)});

        // 3. Conditional variance
        out.put("conditional_variance", new double[]{condVar(0,1), condVar(0,5), condVar(0,10)});

        // 4. Forward bond vol
        double[] fbv = new double[capletMats.length];
        for (int i = 0; i < capletMats.length; i++) {
            double T = capletMats[i];
            double phi = condVar(0, T);
            double bVal = B(T, T + capletTenor);
            fbv[i] = Math.sqrt(phi * bVal * bVal / T);
        }
        out.put("forward_bond_volatility", fbv);

        // 5-12. MC simulation
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

    /**
     * Instantaneous forward rate f(0,t) = d/dt [zr(t)*t].
     * For linear zero-rate interpolation between nodes i and i+1:
     *   zr(t)*t = t*(zr_i + slope*(t-t_i))
     *   d/dt = zr_i + slope*(2t - t_i)
     * where slope = (zr_{i+1}-zr_i)/(t_{i+1}-t_i).
     */
    static double instForward(double t) {
        if (t < zrTenors[0]) return zrRates[0];
        if (t > zrTenors[zrTenors.length - 1]) return zrRates[zrRates.length - 1];
        for (int i = 0; i < zrTenors.length - 1; i++) {
            if (t <= zrTenors[i + 1]) {
                double slope = (zrRates[i + 1] - zrRates[i]) / (zrTenors[i + 1] - zrTenors[i]);
                return zrRates[i] + slope * (2.0 * t - zrTenors[i]);
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

    /** Convexity adjustment: sigma^2/(2a^2)*(1-exp(-a*t))^2. */
    static double phi(double t) {
        double e = 1.0 - Math.exp(-a * t);
        return sigma * sigma / (2.0 * a * a) * e * e;
    }

    /**
     * ln A(t,T) for the HW bond formula P(t,T) = A(t,T)*exp(-B(t,T)*r(t)).
     * ln A = ln(df(T)/df(t)) + B(t,T)*f(0,t) - sigma^2/(4a)*(1-exp(-2at))*B^2
     */
    static double lnA(double t, double T) {
        double bVal = B(t, T);
        double fwd = instForward(t);
        double logDfRatio = Math.log(df(T) / df(t));
        double convex = sigma * sigma / (4.0 * a) * (1.0 - Math.exp(-2.0 * a * t)) * bVal * bVal;
        return logDfRatio + bVal * fwd - convex;
    }

    /** Bond price P(t,T) given short rate r at time t. */
    static double bondPrice(double t, double T, double r) {
        return Math.exp(lnA(t, T) - B(t, T) * r);
    }

    /**
     * Total (non-annualized) lognormal vol of the forward bond P(T,S).
     * sigma_P = (sigma/a)*(1-exp(-a(S-T)))*sqrt((1-exp(-2aT))/(2a))
     */
    static double totalBondVol(double T, double S) {
        return sigma / a * (1.0 - Math.exp(-a * (S - T)))
                * Math.sqrt((1.0 - Math.exp(-2.0 * a * T)) / (2.0 * a));
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

    // ---- Bachelier implied vol ----

    static double bachelierImpliedVol(double forward, double strike, double T,
                                      double payoffUnit, double price) {
        if (price <= 0 || payoffUnit <= 0 || T <= 0) return 0.0;
        double target = price / payoffUnit;
        double sig = target / Math.sqrt(T / (2.0 * Math.PI));
        if (sig <= 0) sig = 1e-8;

        for (int i = 0; i < 200; i++) {
            double sqrtT = Math.sqrt(T);
            double d = (forward - strike) / (sig * sqrtT);
            double val = (forward - strike) * normCDF(d) + sig * sqrtT * normPDF(d);
            double vega = sqrtT * normPDF(d);
            if (vega < 1e-30) break;
            double diff = val - target;
            if (Math.abs(diff) < 1e-14) break;
            sig -= diff / vega;
            if (sig <= 0) sig = 1e-10;
        }
        return sig;
    }

    // ---- Monte Carlo ----

    static void runMonteCarlo(Map<String, Object> out) {
        int nSteps = (int) (horizon / dt);
        double decay = Math.exp(-a * dt);
        double diffusion = sigma * Math.sqrt((1.0 - Math.exp(-2.0 * a * dt)) / (2.0 * a));

        double[][] rates = new double[numPaths][nSteps + 1];
        double[][] logBA = new double[numPaths][nSteps + 1]; // cumulative integral of r

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

            // MC: caplet = E[D(T) * max(1 - (1+Kd)*P(T,T+d), 0)]
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

            // MC implied vol
            mcCapIV[j] = bachelierImpliedVol(F, K, T, payoffUnit, mcCapPrices[j]);

            // Analytic caplet price via zero-bond put
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

    static void priceSwaptions(double[][] rates, double[][] logBA,
                               int nSteps, Map<String, Object> out) {
        // Exercise dates
        List<Double> exDates = new ArrayList<>();
        for (double t = bermFirst; t <= bermLast + 1e-10; t += bermPeriod) {
            exDates.add(Math.round(t * 1000.0) / 1000.0); // clean rounding
        }
        int nEx = exDates.size();

        // Payment dates for the full underlying swap
        List<Double> payDates = new ArrayList<>();
        for (double t = bermFirst + bermPeriod; t <= bermEnd + 1e-10; t += bermPeriod) {
            payDates.add(Math.round(t * 1000.0) / 1000.0);
        }

        // Par swap rate from initial curve
        double annuity0 = 0.0;
        for (double pd : payDates) annuity0 += bermPeriod * df(pd);
        double swapRate = (df(bermFirst) - df(bermEnd)) / annuity0;

        // Intrinsic values at each exercise date for each path
        double[][] intrinsic = new double[numPaths][nEx];

        for (int p = 0; p < numPaths; p++) {
            for (int e = 0; e < nEx; e++) {
                double tEx = exDates.get(e);
                int idx = (int) Math.round(tEx / dt);
                double r = rates[p][idx];

                // Swap value = 1 - P(tEx, bermEnd) - K * sum(delta * P(tEx, payDate))
                // for payment dates >= tEx + bermPeriod
                double localAnnuity = 0.0;
                for (double pd : payDates) {
                    if (pd > tEx + 1e-10) {
                        localAnnuity += bermPeriod * bondPrice(tEx, pd, r);
                    }
                }
                double swapVal = 1.0 - bondPrice(tEx, bermEnd, r) - swapRate * localAnnuity;
                intrinsic[p][e] = Math.max(swapVal, 0.0);
            }
        }

        // --- European swaption (exercise only at first date) ---
        int euroIdx = (int) Math.round(bermFirst / dt);
        double euroSum = 0.0;
        for (int p = 0; p < numPaths; p++) {
            euroSum += Math.exp(-logBA[p][euroIdx]) * intrinsic[p][0];
        }
        out.put("european_swaption_value", euroSum / numPaths);

        // --- Bermudan swaption (Longstaff-Schwartz) ---
        // cashflow[p] = payoff if exercise at exerciseStep[p]
        double[] cashflow = new double[numPaths];
        int[] exerciseStep = new int[numPaths];

        // Initialize at last exercise date
        for (int p = 0; p < numPaths; p++) {
            cashflow[p] = intrinsic[p][nEx - 1];
            exerciseStep[p] = (int) Math.round(exDates.get(nEx - 1) / dt);
        }

        // Backward induction
        for (int e = nEx - 2; e >= 0; e--) {
            double tEx = exDates.get(e);
            int idx = (int) Math.round(tEx / dt);

            // Build ITM set and their continuation values
            List<Integer> itm = new ArrayList<>();
            double[] contVal = new double[numPaths];

            for (int p = 0; p < numPaths; p++) {
                // Discounted continuation: cashflow * D(exerciseStep)/D(idx)
                contVal[p] = cashflow[p] * Math.exp(-(logBA[p][exerciseStep[p]] - logBA[p][idx]));
                if (intrinsic[p][e] > 1e-12) {
                    itm.add(p);
                }
            }

            if (itm.size() < 4) continue; // not enough points for regression

            // OLS regression: contVal ~ b0 + b1*r + b2*r^2
            int n = itm.size();
            double[] rVals = new double[n];
            double[] yVals = new double[n];
            for (int i = 0; i < n; i++) {
                int p = itm.get(i);
                rVals[i] = rates[p][idx];
                yVals[i] = contVal[p];
            }

            double[] beta = fitQuadratic(rVals, yVals);

            // Exercise decision: exercise if intrinsic >= estimated continuation
            for (int ip : itm) {
                double r = rates[ip][idx];
                double estCont = beta[0] + beta[1] * r + beta[2] * r * r;
                if (intrinsic[ip][e] >= estCont) {
                    cashflow[ip] = intrinsic[ip][e];
                    exerciseStep[ip] = idx;
                }
            }
        }

        // Bermudan value = mean of discounted cashflows
        double bermSum = 0.0;
        for (int p = 0; p < numPaths; p++) {
            bermSum += Math.exp(-logBA[p][exerciseStep[p]]) * cashflow[p];
        }
        out.put("bermudan_swaption_value", bermSum / numPaths);
    }

    /** Fit y = b0 + b1*x + b2*x^2 via normal equations. */
    static double[] fitQuadratic(double[] x, double[] y) {
        int n = x.length;
        // X'X and X'y for 3 coefficients
        double s0 = n, s1 = 0, s2 = 0, s3 = 0, s4 = 0;
        double sy0 = 0, sy1 = 0, sy2 = 0;
        for (int i = 0; i < n; i++) {
            double xi = x[i];
            double x2 = xi * xi;
            s1 += xi;
            s2 += x2;
            s3 += x2 * xi;
            s4 += x2 * x2;
            sy0 += y[i];
            sy1 += y[i] * xi;
            sy2 += y[i] * x2;
        }

        // Solve 3x3: [s0 s1 s2; s1 s2 s3; s2 s3 s4] * b = [sy0; sy1; sy2]
        double[][] A = {{s0, s1, s2}, {s1, s2, s3}, {s2, s3, s4}};
        double[] b = {sy0, sy1, sy2};
        return solve3(A, b);
    }

    /** Solve 3x3 system by Gaussian elimination with partial pivoting. */
    static double[] solve3(double[][] A, double[] b) {
        int n = 3;
        double[][] M = new double[n][n + 1];
        for (int i = 0; i < n; i++) {
            System.arraycopy(A[i], 0, M[i], 0, n);
            M[i][n] = b[i];
        }
        for (int col = 0; col < n; col++) {
            int pivot = col;
            for (int row = col + 1; row < n; row++)
                if (Math.abs(M[row][col]) > Math.abs(M[pivot][col])) pivot = row;
            double[] tmp = M[col]; M[col] = M[pivot]; M[pivot] = tmp;

            if (Math.abs(M[col][col]) < 1e-30) continue;
            for (int row = col + 1; row < n; row++) {
                double f = M[row][col] / M[col][col];
                for (int j = col; j <= n; j++) M[row][j] -= f * M[col][j];
            }
        }
        double[] x = new double[n];
        for (int i = n - 1; i >= 0; i--) {
            double s = M[i][n];
            for (int j = i + 1; j < n; j++) s -= M[i][j] * x[j];
            x[i] = Math.abs(M[i][i]) > 1e-30 ? s / M[i][i] : 0.0;
        }
        return x;
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
