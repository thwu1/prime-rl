package cds;

import java.io.*;
import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;

/**
 * ISDA CDS Standard Model Pricer — skeleton.
 *
 *
 * Implement the CDS pricing logic to compute protection leg,
 * dirty risky annuity, and clean present value for each trade
 * defined in /app/data/trades.json using curves from the CSV files.
 * Write results to /app/results.json.
 */
public class CdsPricer {

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: CdsPricer <data_dir>");
            System.exit(1);
        }
        String dataDir = args[0];

        // Load market data from external files
        double[][] yieldCurve = DataLoader.loadCurve(dataDir + "/yield_curve.csv");
        double[][] creditCurve = DataLoader.loadCurve(dataDir + "/credit_curve.csv");
        List<Trade> trades = DataLoader.loadTrades(dataDir + "/trades.json");

        double[] ycTimes = yieldCurve[0];
        double[] ycRates = yieldCurve[1];
        double[] ccTimes = creditCurve[0];
        double[] ccRates = creditCurve[1];

        // TODO: Implement CDS pricing for each trade.
        //
        // For each trade, compute:
        //   - protection_leg  (per unit notional)
        //   - dirty_annuity   (per unit notional)
        //   - clean_pv        (currency amount)
        //
        // Model conventions are specified in trades.json under "model_conventions".
        // Curves loaded above provide the discount and survival curve nodes.

        Map<String, Double> results = new LinkedHashMap<>();
        for (Trade t : trades) {
            results.put(t.id + "_protection_leg", 0.0);
            results.put(t.id + "_dirty_annuity", 0.0);
            results.put(t.id + "_clean_pv", 0.0);
        }

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
