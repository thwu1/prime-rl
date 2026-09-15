package cds;

import java.io.*;
import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;

/**
 * ISDA CDS Standard Model Pricer - Complete Implementation.
 *
 *
 * Implements product-linear interpolation, CDS schedule generation,
 * protection leg integration, premium leg with ORIGINAL_ISDA
 * accrual-on-default, and clean PV computation.
 */
public class CdsPricer {

    // =========================================================================
    // MARKET DATA
    // =========================================================================
    static final LocalDate VALUATION_DATE = LocalDate.of(2014, 1, 3);

    static final double[] YC_TIMES = {
        0.09041095890410959, 0.16712328767123288, 0.2547945205479452,
        0.5041095890410959, 0.7534246575342466, 1.0054794520547945,
        2.0054794520547947, 3.008219178082192, 4.013698630136987,
        5.010958904109589, 6.008219178082192, 7.010958904109589,
        8.01095890410959, 9.01095890410959, 10.016438356164384,
        12.013698630136986, 15.021917808219179, 20.01917808219178,
        30.024657534246575
    };

    static final double[] YC_RATES = {
        -0.002078655697855299, -0.001686438401304855, -0.0013445486228483379,
        -4.237819925898475E-4, 2.5142499469348057E-5, 5.935063895780138E-4,
        -3.247081037469503E-4, 6.147182786549223E-4, 0.0019060597240545122,
        0.0033125742254568815, 0.0047766352312329455, 0.0062374324537341225,
        0.007639664176639106, 0.008971003650150983, 0.010167545380711455,
        0.012196853322376243, 0.01441082634734099, 0.016236611610989507,
        0.01652439910865982
    };

    static final double[] CC_TIMES = {
        1.2054794520547945, 1.7095890410958905, 2.712328767123288,
        3.712328767123288, 4.712328767123288, 5.712328767123288,
        7.715068493150685, 10.717808219178082
    };

    static final double[] CC_RATES = {
        0.009950492020354761, 0.01203385973637765, 0.01418821591480718,
        0.01684815168721049, 0.01974873350586718, 0.023084203422383043,
        0.02696911931489543, 0.029605642651816415
    };

    static final double NOTIONAL = 1.0e7;
    static final double FIXED_RATE = 0.05;
    static final double RECOVERY_RATE = 0.25;
    static final LocalDate STEPIN_DATE = LocalDate.of(2014, 1, 4);

    // =========================================================================
    // INTERPOLATION: Product-linear (r*t is piecewise linear)
    // =========================================================================

    static double curveProduct(double[] times, double[] rates, double t) {
        int n = times.length;
        if (t <= times[0]) {
            return rates[0] * t;
        }
        if (t >= times[n - 1]) {
            double p_prev = times[n - 2] * rates[n - 2];
            double p_last = times[n - 1] * rates[n - 1];
            double slope = (p_last - p_prev) / (times[n - 1] - times[n - 2]);
            return p_last + slope * (t - times[n - 1]);
        }
        int lo = 0, hi = n - 1;
        while (lo < hi - 1) {
            int mid = (lo + hi) >>> 1;
            if (times[mid] <= t) lo = mid;
            else hi = mid;
        }
        double p_lo = times[lo] * rates[lo];
        double p_hi = times[hi] * rates[hi];
        double frac = (t - times[lo]) / (times[hi] - times[lo]);
        return p_lo + (p_hi - p_lo) * frac;
    }

    static double discountFactor(double t) {
        if (t <= 0) return 1.0;
        return Math.exp(-curveProduct(YC_TIMES, YC_RATES, t));
    }

    static double survivalProbability(double t) {
        if (t <= 0) return 1.0;
        return Math.exp(-curveProduct(CC_TIMES, CC_RATES, t));
    }

    // =========================================================================
    // DATE UTILITIES
    // =========================================================================

    static double yf365(LocalDate from, LocalDate to) {
        return ChronoUnit.DAYS.between(from, to) / 365.0;
    }

    static double yf360(LocalDate from, LocalDate to) {
        return ChronoUnit.DAYS.between(from, to) / 360.0;
    }

    static boolean isBusinessDay(LocalDate d) {
        DayOfWeek dow = d.getDayOfWeek();
        return dow != DayOfWeek.SATURDAY && dow != DayOfWeek.SUNDAY;
    }

    static LocalDate adjustFollowing(LocalDate d) {
        while (!isBusinessDay(d)) d = d.plusDays(1);
        return d;
    }

    // =========================================================================
    // SCHEDULE GENERATION
    // =========================================================================

    static List<LocalDate[]> generateSchedule(LocalDate startDate, LocalDate endDate) {
        int rollDay = endDate.getDayOfMonth();
        List<LocalDate> unadjDates = new ArrayList<>();
        unadjDates.add(endDate);
        LocalDate current = endDate;
        while (true) {
            current = current.minusMonths(3);
            int dom = Math.min(rollDay, current.lengthOfMonth());
            current = LocalDate.of(current.getYear(), current.getMonth(), dom);
            if (current.compareTo(startDate) <= 0) {
                break;
            }
            unadjDates.add(current);
        }
        unadjDates.add(startDate);
        Collections.reverse(unadjDates);
        List<LocalDate> adjDates = new ArrayList<>();
        for (int i = 0; i < unadjDates.size(); i++) {
            if (i == 0 || i == unadjDates.size() - 1) {
                adjDates.add(unadjDates.get(i));
            } else {
                adjDates.add(adjustFollowing(unadjDates.get(i)));
            }
        }
        List<LocalDate[]> periods = new ArrayList<>();
        for (int i = 0; i < adjDates.size() - 1; i++) {
            periods.add(new LocalDate[]{adjDates.get(i), adjDates.get(i + 1)});
        }
        return periods;
    }

    // =========================================================================
    // EPSILON FUNCTIONS
    // =========================================================================

    static double epsilon(double x) {
        if (Math.abs(x) < 1e-5) {
            return 1.0 - x / 2.0 + x * x / 6.0 - x * x * x / 24.0 + x * x * x * x / 120.0;
        }
        return (1.0 - Math.exp(-x)) / x;
    }

    static double epsilonP(double x) {
        if (Math.abs(x) < 1e-5) {
            return 0.5 - x / 3.0 + x * x / 8.0 - x * x * x / 30.0 + x * x * x * x / 144.0;
        }
        return (1.0 - (1.0 + x) * Math.exp(-x)) / (x * x);
    }

    // =========================================================================
    // MERGE KNOT TIMES
    // =========================================================================

    static double[] getIntegrationKnots(double tStart, double tEnd) {
        TreeSet<Double> knots = new TreeSet<>();
        knots.add(tStart);
        knots.add(tEnd);
        for (double t : YC_TIMES) {
            if (t > tStart && t < tEnd) knots.add(t);
        }
        for (double t : CC_TIMES) {
            if (t > tStart && t < tEnd) knots.add(t);
        }
        double[] result = new double[knots.size()];
        int i = 0;
        for (double t : knots) result[i++] = t;
        return result;
    }

    // =========================================================================
    // PROTECTION LEG
    // =========================================================================

    static double protectionLeg(LocalDate protStartDate, LocalDate protEndDate) {
        double tStart = yf365(VALUATION_DATE, protStartDate);
        double tEnd = yf365(VALUATION_DATE, protEndDate);
        if (tEnd <= tStart) return 0.0;
        double lgd = 1.0 - RECOVERY_RATE;
        double[] knots = getIntegrationKnots(tStart, tEnd);
        double protLeg = 0.0;
        double ccRt0 = curveProduct(CC_TIMES, CC_RATES, knots[0]);
        double ycRt0 = curveProduct(YC_TIMES, YC_RATES, knots[0]);
        double q0 = Math.exp(-ccRt0);
        double b0 = Math.exp(-ycRt0);
        for (int i = 1; i < knots.length; i++) {
            double ccRt1 = curveProduct(CC_TIMES, CC_RATES, knots[i]);
            double ycRt1 = curveProduct(YC_TIMES, YC_RATES, knots[i]);
            double q1 = Math.exp(-ccRt1);
            double b1 = Math.exp(-ycRt1);
            double dht = ccRt1 - ccRt0;
            double drt = ycRt1 - ycRt0;
            double dhrt = dht + drt;
            double dPV;
            if (Math.abs(dhrt) < 1e-5) {
                dPV = dht * q0 * b0 * epsilon(dhrt);
            } else {
                dPV = dht / dhrt * (q0 * b0 - q1 * b1);
            }
            protLeg += dPV;
            ccRt0 = ccRt1;
            ycRt0 = ycRt1;
            q0 = q1;
            b0 = b1;
        }
        return lgd * protLeg;
    }

    // =========================================================================
    // PREMIUM LEG (DIRTY RISKY ANNUITY)
    // =========================================================================

    static double dirtyRiskyAnnuity(List<LocalDate[]> schedule) {
        double annuity = 0.0;
        for (LocalDate[] period : schedule) {
            LocalDate accStart = period[0];
            LocalDate accEnd = period[1];
            double tEnd = yf365(VALUATION_DATE, accEnd);
            if (tEnd <= 0) continue;
            double delta = yf360(accStart, accEnd);
            double qEnd = survivalProbability(tEnd);
            double bEnd = discountFactor(tEnd);
            annuity += delta * qEnd * bEnd;
            double tAccStart = yf365(VALUATION_DATE, accStart);
            double tAccEnd = tEnd;
            double tEffStart = Math.max(tAccStart, yf365(VALUATION_DATE, STEPIN_DATE));
            if (tEffStart >= tAccEnd) continue;
            double accPeriodLength = tAccEnd - tAccStart;
            if (accPeriodLength <= 0) continue;
            double[] knots = getIntegrationKnots(tEffStart, tAccEnd);
            double ccRt0 = curveProduct(CC_TIMES, CC_RATES, knots[0]);
            double ycRt0 = curveProduct(YC_TIMES, YC_RATES, knots[0]);
            double q0 = Math.exp(-ccRt0);
            double b0 = Math.exp(-ycRt0);
            for (int i = 1; i < knots.length; i++) {
                double ccRt1 = curveProduct(CC_TIMES, CC_RATES, knots[i]);
                double ycRt1 = curveProduct(YC_TIMES, YC_RATES, knots[i]);
                double q1 = Math.exp(-ccRt1);
                double b1 = Math.exp(-ycRt1);
                double lambda = ccRt1 - ccRt0;
                double mu = ycRt1 - ycRt0;
                double lambdaPlusMu = lambda + mu;
                double s0 = (knots[i - 1] - tAccStart) / accPeriodLength;
                double s1 = (knots[i] - tAccStart) / accPeriodLength;
                double accContrib;
                if (Math.abs(lambdaPlusMu) < 1e-5) {
                    double eps = epsilon(lambdaPlusMu);
                    double epsP = epsilonP(lambdaPlusMu);
                    accContrib = lambda * q0 * b0 * (s0 * eps + (s1 - s0) * epsP);
                } else {
                    double qb0 = q0 * b0;
                    double qb1 = q1 * b1;
                    double dqb = qb0 - qb1;
                    accContrib = lambda / lambdaPlusMu *
                        (s0 * dqb + (s1 - s0) * (dqb / lambdaPlusMu - qb1));
                }
                annuity += delta * accContrib;
                ccRt0 = ccRt1;
                ycRt0 = ycRt1;
                q0 = q1;
                b0 = b1;
            }
        }
        return annuity;
    }

    // =========================================================================
    // CLEAN PV
    // =========================================================================

    static double[] computeTrade(int buySell, LocalDate startDate, LocalDate endDate) {
        List<LocalDate[]> schedule = generateSchedule(startDate, endDate);
        LocalDate protStart = startDate.isAfter(STEPIN_DATE) ? startDate : STEPIN_DATE;
        LocalDate protEnd = endDate;
        double protLeg = protectionLeg(protStart, protEnd);
        double dirtyAnnuity = dirtyRiskyAnnuity(schedule);
        double accruedYF = 0.0;
        for (LocalDate[] period : schedule) {
            LocalDate accStart = period[0];
            LocalDate accEnd = period[1];
            if (!STEPIN_DATE.isAfter(accStart) || STEPIN_DATE.isAfter(accEnd)) continue;
            accruedYF = yf360(accStart, STEPIN_DATE);
            break;
        }
        double cleanAnnuity = dirtyAnnuity - accruedYF;
        double cleanPrice = protLeg - FIXED_RATE * cleanAnnuity;
        double cleanPV = buySell * NOTIONAL * cleanPrice;
        return new double[]{protLeg, dirtyAnnuity, cleanPV};
    }

    // =========================================================================
    // MAIN
    // =========================================================================

    public static void main(String[] args) throws Exception {
        Map<String, Double> results = new LinkedHashMap<>();
        double[] nextday = computeTrade(1, LocalDate.of(2014, 1, 4), LocalDate.of(2020, 10, 20));
        results.put("nextday_protection_leg", nextday[0]);
        results.put("nextday_dirty_annuity", nextday[1]);
        results.put("nextday_clean_pv", nextday[2]);
        double[] before = computeTrade(-1, LocalDate.of(2013, 12, 20), LocalDate.of(2024, 9, 20));
        results.put("before_protection_leg", before[0]);
        results.put("before_dirty_annuity", before[1]);
        results.put("before_clean_pv", before[2]);
        double[] after = computeTrade(1, LocalDate.of(2014, 3, 20), LocalDate.of(2029, 12, 20));
        results.put("after_protection_leg", after[0]);
        results.put("after_dirty_annuity", after[1]);
        results.put("after_clean_pv", after[2]);
        writeJson(results, "/app/results.json");
        for (Map.Entry<String, Double> e : results.entrySet()) {
            System.out.printf("%s = %.17g%n", e.getKey(), e.getValue());
        }
    }

    static void writeJson(Map<String, Double> map, String path) throws Exception {
        try (PrintWriter pw = new PrintWriter(new FileWriter(path))) {
            pw.println("{");
            int i = 0;
            for (Map.Entry<String, Double> e : map.entrySet()) {
                pw.printf("  \"%s\": %.17g", e.getKey(), e.getValue());
                if (++i < map.size()) pw.println(",");
                else pw.println();
            }
            pw.println("}");
        }
    }
}
