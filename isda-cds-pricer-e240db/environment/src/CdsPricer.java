import java.io.*;
import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;

/**
 * ISDA CDS Standard Model Pricer.
 *
 *
 * Implement the ISDA-compliant CDS pricing model to compute protection leg,
 * dirty risky annuity, and clean present value for three CDS trades.
 * Output results to /app/results.json.
 */
public class CdsPricer {

    // =========================================================================
    // MARKET DATA: Pre-calibrated yield curve (USD, ACT/365F, product-linear)
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

    // =========================================================================
    // MARKET DATA: Pre-calibrated credit curve (ACT/365F, product-linear)
    // =========================================================================
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

    // =========================================================================
    // TRADE PARAMETERS
    // =========================================================================
    static final double NOTIONAL = 1.0e7;
    static final double FIXED_RATE = 0.05;
    static final double RECOVERY_RATE = 0.25;

    // PRODUCT_NEXTDAY: BUY, start 2014-01-04, end 2020-10-20, P3M, SAT_SUN
    // PRODUCT_BEFORE:  SELL, start 2013-12-20, end 2024-09-20, P3M, SAT_SUN
    // PRODUCT_AFTER:   BUY, start 2014-03-20, end 2029-12-20, P3M, SAT_SUN

    // Step-in: T+1 calendar = 2014-01-04
    // Settlement: T+3 business (SAT_SUN) = 2014-01-08

    static final LocalDate STEPIN_DATE = LocalDate.of(2014, 1, 4);

    // =========================================================================
    // MAIN: Compute results and write to /app/results.json
    // =========================================================================
    public static void main(String[] args) throws Exception {
        // TODO: Implement CDS pricing logic and produce results.json
        //
        // Required output keys in results.json (flat JSON):
        //   nextday_protection_leg, nextday_dirty_annuity, nextday_clean_pv
        //   before_protection_leg, before_dirty_annuity, before_clean_pv
        //   after_protection_leg, after_dirty_annuity, after_clean_pv

        Map<String, Double> results = new LinkedHashMap<>();
        results.put("nextday_protection_leg", 0.0);
        results.put("nextday_dirty_annuity", 0.0);
        results.put("nextday_clean_pv", 0.0);
        results.put("before_protection_leg", 0.0);
        results.put("before_dirty_annuity", 0.0);
        results.put("before_clean_pv", 0.0);
        results.put("after_protection_leg", 0.0);
        results.put("after_dirty_annuity", 0.0);
        results.put("after_clean_pv", 0.0);

        writeJson(results, "/app/results.json");
        System.out.println("Results written to /app/results.json");
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

    // =========================================================================
    // UTILITY: ACT/365F year fraction
    // =========================================================================
    static double yearFraction365F(LocalDate from, LocalDate to) {
        return ChronoUnit.DAYS.between(from, to) / 365.0;
    }

    // =========================================================================
    // UTILITY: ACT/360 year fraction
    // =========================================================================
    static double yearFraction360(LocalDate from, LocalDate to) {
        return ChronoUnit.DAYS.between(from, to) / 360.0;
    }

    // =========================================================================
    // UTILITY: SAT_SUN calendar business day check
    // =========================================================================
    static boolean isBusinessDay(LocalDate date) {
        DayOfWeek dow = date.getDayOfWeek();
        return dow != DayOfWeek.SATURDAY && dow != DayOfWeek.SUNDAY;
    }

    // =========================================================================
    // UTILITY: FOLLOWING business day adjustment
    // =========================================================================
    static LocalDate adjustFollowing(LocalDate date) {
        while (!isBusinessDay(date)) {
            date = date.plusDays(1);
        }
        return date;
    }
}
