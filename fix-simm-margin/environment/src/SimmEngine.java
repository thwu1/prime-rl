import java.math.*;
import java.util.*;
import java.util.stream.*;

/**
 * ISDA SIMM v2.5 1-Day Holding Period Delta Margin Engine.
 *
 * For 1-day holding period, concentration thresholds are disabled (CR=1.0).
 *
 */
public class SimmEngine {

    static final MathContext MC = new MathContext(30, RoundingMode.HALF_UP);

    static final String RT_IR = "Risk_IRCurve";
    static final String RT_INFLATION = "Risk_Inflation";
    static final String RT_XCCY = "Risk_XCcyBasis";
    static final String RT_FX = "Risk_FX";
    static final String RT_CRQ = "Risk_CreditQ";
    static final String RT_CRNQ = "Risk_CreditNonQ";
    static final String RT_EQ = "Risk_Equity";
    static final String RT_CM = "Risk_Commodity";
    static final String RT_BC = "Risk_BaseCorr";

    // ===== IR PARAMETERS (1-day) =====
    static final Set<String> IR_REGULAR = new HashSet<>(Arrays.asList(
        "USD","EUR","GBP","AUD","CAD","CHF","DKK","HKD","KRW","NOK","NZD","SEK","SGD","TWD"));
    static final Set<String> IR_LOW_VOL = new HashSet<>(Arrays.asList("JPY"));

    static final String[] TENORS = {"2w","1m","3m","6m","1y","2y","3y","5y","10y","15y","20y","30y"};
    static final Map<String, Integer> TENOR_IDX = new HashMap<>();
    static { for (int i = 0; i < TENORS.length; i++) TENOR_IDX.put(TENORS[i], i); }

    // [volType][tenorIdx] - 0=Regular, 1=Low, 2=High
    static final BigDecimal[][] IR_RW = {
        {bd("19"),bd("16"),bd("12"),bd("12"),bd("13"),bd("16"),bd("16"),bd("16"),bd("16"),bd("17"),bd("16"),bd("17")},
        {bd("1.7"),bd("3.4"),bd("1.8"),bd("2.0"),bd("3.3"),bd("4.8"),bd("5.8"),bd("6.8"),bd("6.5"),bd("7.0"),bd("7.5"),bd("8.3")},
        {bd("49"),bd("24"),bd("16"),bd("20"),bd("23"),bd("23"),bd("33"),bd("31"),bd("34"),bd("33"),bd("33"),bd("27")}
    };
    static final BigDecimal IR_INFLATION_RW = bd("15");
    static final BigDecimal IR_XCCY_RW = bd("5.9");

    static final BigDecimal IR_SUB_CURVE_CORR = bd("0.37");  // sub-curve same-currency correlation
    static final BigDecimal IR_INFLATION_CORR = bd("0.99");   // inflation to IR curve correlation
    static final BigDecimal IR_XCCY_CORR = bd("0.01");
    static final BigDecimal IR_GAMMA = bd("0.24");

    static final BigDecimal[][] IR_TENOR_CORR = {
        {bd("1"),bd("0.74"),bd("0.63"),bd("0.55"),bd("0.45"),bd("0.36"),bd("0.32"),bd("0.28"),bd("0.23"),bd("0.2"),bd("0.18"),bd("0.16")},
        {bd("0.74"),bd("1"),bd("0.8"),bd("0.69"),bd("0.52"),bd("0.41"),bd("0.35"),bd("0.29"),bd("0.24"),bd("0.18"),bd("0.17"),bd("0.16")},
        {bd("0.63"),bd("0.8"),bd("1"),bd("0.85"),bd("0.67"),bd("0.53"),bd("0.45"),bd("0.39"),bd("0.32"),bd("0.24"),bd("0.22"),bd("0.22")},
        {bd("0.55"),bd("0.69"),bd("0.85"),bd("1"),bd("0.83"),bd("0.71"),bd("0.62"),bd("0.54"),bd("0.45"),bd("0.36"),bd("0.35"),bd("0.33")},
        {bd("0.45"),bd("0.52"),bd("0.67"),bd("0.83"),bd("1"),bd("0.94"),bd("0.86"),bd("0.78"),bd("0.65"),bd("0.58"),bd("0.55"),bd("0.53")},
        {bd("0.36"),bd("0.41"),bd("0.53"),bd("0.71"),bd("0.94"),bd("1"),bd("0.95"),bd("0.89"),bd("0.78"),bd("0.72"),bd("0.68"),bd("0.67")},
        {bd("0.32"),bd("0.35"),bd("0.45"),bd("0.62"),bd("0.86"),bd("0.95"),bd("1"),bd("0.96"),bd("0.87"),bd("0.8"),bd("0.77"),bd("0.74")},
        {bd("0.28"),bd("0.29"),bd("0.39"),bd("0.54"),bd("0.78"),bd("0.89"),bd("0.96"),bd("1"),bd("0.94"),bd("0.89"),bd("0.86"),bd("0.84")},
        {bd("0.23"),bd("0.24"),bd("0.32"),bd("0.45"),bd("0.65"),bd("0.78"),bd("0.87"),bd("0.94"),bd("1"),bd("0.97"),bd("0.95"),bd("0.94")},
        {bd("0.2"),bd("0.18"),bd("0.24"),bd("0.36"),bd("0.58"),bd("0.72"),bd("0.8"),bd("0.89"),bd("0.97"),bd("1"),bd("0.98"),bd("0.98")},
        {bd("0.18"),bd("0.17"),bd("0.22"),bd("0.35"),bd("0.55"),bd("0.68"),bd("0.77"),bd("0.86"),bd("0.95"),bd("0.98"),bd("1"),bd("0.99")},
        {bd("0.16"),bd("0.16"),bd("0.22"),bd("0.33"),bd("0.53"),bd("0.67"),bd("0.74"),bd("0.84"),bd("0.94"),bd("0.98"),bd("0.99"),bd("1")}
    };

    // ===== FX PARAMETERS (1-day) =====
    static final Set<String> FX_HIGH_VOL = new HashSet<>(Arrays.asList("TRY", "ZAR", "RUB"));
    static final BigDecimal[][] FX_RW = {{bd("1.8"),bd("3.2")},{bd("3.2"),bd("3.4")}};
    static final BigDecimal[][] FX_CORR_REG = {{bd("0.5"),bd("0.27")},{bd("0.27"),bd("0.42")}};
    static final BigDecimal[][] FX_CORR_HIGH = {{bd("0.85"),bd("0.54")},{bd("0.54"),bd("0.5")}};

    // ===== CRQ PARAMETERS (1-day) =====
    static final BigDecimal[] CRQ_RW = {bd("0"),bd("21"),bd("27"),bd("16"),bd("12"),bd("14"),bd("12"),bd("48"),bd("144"),bd("51"),bd("53"),bd("38"),bd("57")};
    static final BigDecimal CRQ_RW_RES = bd("144");
    static final BigDecimal CRQ_SAME = bd("0.93"), CRQ_DIFF = bd("0.42"), CRQ_RES = bd("0.5");
    static final BigDecimal[][] CRQ_GAMMA = {
        {null,bd("0.36"),bd("0.38"),bd("0.35"),bd("0.37"),bd("0.33"),bd("0.36"),bd("0.31"),bd("0.32"),bd("0.33"),bd("0.32"),bd("0.3")},
        {bd("0.36"),null,bd("0.46"),bd("0.44"),bd("0.45"),bd("0.43"),bd("0.33"),bd("0.36"),bd("0.38"),bd("0.39"),bd("0.4"),bd("0.36")},
        {bd("0.38"),bd("0.46"),null,bd("0.49"),bd("0.49"),bd("0.47"),bd("0.34"),bd("0.36"),bd("0.41"),bd("0.42"),bd("0.43"),bd("0.39")},
        {bd("0.35"),bd("0.44"),bd("0.49"),null,bd("0.48"),bd("0.48"),bd("0.31"),bd("0.34"),bd("0.38"),bd("0.42"),bd("0.41"),bd("0.37")},
        {bd("0.37"),bd("0.45"),bd("0.49"),bd("0.48"),null,bd("0.48"),bd("0.33"),bd("0.35"),bd("0.39"),bd("0.42"),bd("0.43"),bd("0.38")},
        {bd("0.33"),bd("0.43"),bd("0.47"),bd("0.48"),bd("0.48"),null,bd("0.29"),bd("0.32"),bd("0.36"),bd("0.39"),bd("0.4"),bd("0.35")},
        {bd("0.36"),bd("0.33"),bd("0.34"),bd("0.31"),bd("0.33"),bd("0.29"),null,bd("0.28"),bd("0.32"),bd("0.31"),bd("0.3"),bd("0.28")},
        {bd("0.31"),bd("0.36"),bd("0.36"),bd("0.34"),bd("0.35"),bd("0.32"),bd("0.28"),null,bd("0.33"),bd("0.34"),bd("0.33"),bd("0.3")},
        {bd("0.32"),bd("0.38"),bd("0.41"),bd("0.38"),bd("0.39"),bd("0.36"),bd("0.32"),bd("0.33"),null,bd("0.38"),bd("0.36"),bd("0.34")},
        {bd("0.33"),bd("0.39"),bd("0.42"),bd("0.42"),bd("0.42"),bd("0.39"),bd("0.31"),bd("0.34"),bd("0.38"),null,bd("0.38"),bd("0.36")},
        {bd("0.32"),bd("0.4"),bd("0.43"),bd("0.41"),bd("0.43"),bd("0.4"),bd("0.3"),bd("0.33"),bd("0.36"),bd("0.38"),null,bd("0.35")},
        {bd("0.3"),bd("0.36"),bd("0.39"),bd("0.37"),bd("0.38"),bd("0.35"),bd("0.28"),bd("0.3"),bd("0.34"),bd("0.36"),bd("0.35"),null}
    };

    // ===== CRNQ PARAMETERS (1-day) =====
    static final BigDecimal CRNQ_RW_1 = bd("66"), CRNQ_RW_2 = bd("250"), CRNQ_RW_RES = bd("250");
    static final BigDecimal CRNQ_SAME = bd("0.82"), CRNQ_DIFF = bd("0.27"), CRNQ_RES = bd("0.5");
    static final BigDecimal CRNQ_GAMMA_VAL = bd("0.4");

    // ===== EQUITY PARAMETERS (1-day) =====
    static final BigDecimal[] EQ_RW = {bd("0"),bd("9.3"),bd("9.7"),bd("10.0"),bd("9.2"),bd("7.7"),bd("8.5"),bd("9.5"),bd("9.6"),bd("10.0"),bd("10"),bd("5.9"),bd("5.9")};
    static final BigDecimal EQ_RW_RES = bd("10.0");
    static final BigDecimal[] EQ_INTRA = {bd("0"),bd("0.18"),bd("0.23"),bd("0.3"),bd("0.26"),bd("0.23"),bd("0.35"),bd("0.36"),bd("0.33"),bd("0.19"),bd("0.2"),bd("0.45"),bd("0.45")};
    static final BigDecimal[][] EQ_GAMMA = {
        {null,bd("0.2"),bd("0.2"),bd("0.2"),bd("0.13"),bd("0.16"),bd("0.16"),bd("0.16"),bd("0.17"),bd("0.12"),bd("0.18"),bd("0.18")},
        {bd("0.2"),null,bd("0.25"),bd("0.23"),bd("0.14"),bd("0.17"),bd("0.18"),bd("0.17"),bd("0.19"),bd("0.13"),bd("0.19"),bd("0.19")},
        {bd("0.2"),bd("0.25"),null,bd("0.24"),bd("0.13"),bd("0.17"),bd("0.18"),bd("0.16"),bd("0.2"),bd("0.13"),bd("0.18"),bd("0.18")},
        {bd("0.2"),bd("0.23"),bd("0.24"),null,bd("0.17"),bd("0.22"),bd("0.22"),bd("0.22"),bd("0.21"),bd("0.16"),bd("0.24"),bd("0.24")},
        {bd("0.13"),bd("0.14"),bd("0.13"),bd("0.17"),null,bd("0.27"),bd("0.26"),bd("0.27"),bd("0.15"),bd("0.2"),bd("0.3"),bd("0.3")},
        {bd("0.16"),bd("0.17"),bd("0.17"),bd("0.22"),bd("0.27"),null,bd("0.34"),bd("0.33"),bd("0.18"),bd("0.24"),bd("0.38"),bd("0.38")},
        {bd("0.16"),bd("0.18"),bd("0.18"),bd("0.22"),bd("0.26"),bd("0.34"),null,bd("0.32"),bd("0.18"),bd("0.24"),bd("0.37"),bd("0.37")},
        {bd("0.16"),bd("0.17"),bd("0.16"),bd("0.22"),bd("0.27"),bd("0.33"),bd("0.32"),null,bd("0.18"),bd("0.23"),bd("0.37"),bd("0.37")},
        {bd("0.17"),bd("0.19"),bd("0.2"),bd("0.21"),bd("0.15"),bd("0.18"),bd("0.18"),bd("0.18"),null,bd("0.14"),bd("0.2"),bd("0.2")},
        {bd("0.12"),bd("0.13"),bd("0.13"),bd("0.16"),bd("0.2"),bd("0.24"),bd("0.24"),bd("0.23"),bd("0.14"),null,bd("0.25"),bd("0.25")},
        {bd("0.18"),bd("0.19"),bd("0.18"),bd("0.24"),bd("0.3"),bd("0.38"),bd("0.37"),bd("0.37"),bd("0.2"),bd("0.25"),null,bd("0.45")},
        {bd("0.18"),bd("0.19"),bd("0.18"),bd("0.24"),bd("0.3"),bd("0.38"),bd("0.37"),bd("0.37"),bd("0.2"),bd("0.25"),bd("0.45"),null}
    };

    // ===== COMMODITY PARAMETERS (1-day) =====
    static final BigDecimal[] CM_RW = {bd("0"),bd("9.0"),bd("9.1"),bd("8.1"),bd("7.2"),bd("10"),bd("8.2"),bd("9.7"),bd("10"),bd("10"),bd("16"),bd("6.2"),bd("6.5"),bd("4.6"),bd("4.6"),bd("4.0"),bd("16"),bd("5.1")};
    static final BigDecimal[] CM_INTRA = {bd("0"),bd("0.84"),bd("0.98"),bd("0.96"),bd("0.97"),bd("0.98"),bd("0.88"),bd("0.98"),bd("0.49"),bd("0.8"),bd("0.46"),bd("0.55"),bd("0.46"),bd("0.66"),bd("0.18"),bd("0.21"),bd("0"),bd("0.36")};
    static final BigDecimal[][] CM_GAMMA = {
        {null,bd("0.33"),bd("0.21"),bd("0.27"),bd("0.29"),bd("0.21"),bd("0.48"),bd("0.16"),bd("0.41"),bd("0.23"),bd("0.18"),bd("0.02"),bd("0.21"),bd("0.19"),bd("0.15"),bd("0"),bd("0.24")},
        {bd("0.33"),null,bd("0.94"),bd("0.94"),bd("0.89"),bd("0.21"),bd("0.19"),bd("0.13"),bd("0.21"),bd("0.21"),bd("0.41"),bd("0.27"),bd("0.31"),bd("0.29"),bd("0.21"),bd("0"),bd("0.6")},
        {bd("0.21"),bd("0.94"),null,bd("0.91"),bd("0.85"),bd("0.12"),bd("0.2"),bd("0.09"),bd("0.19"),bd("0.2"),bd("0.36"),bd("0.18"),bd("0.22"),bd("0.23"),bd("0.23"),bd("0"),bd("0.54")},
        {bd("0.27"),bd("0.94"),bd("0.91"),null,bd("0.84"),bd("0.14"),bd("0.24"),bd("0.13"),bd("0.21"),bd("0.19"),bd("0.39"),bd("0.25"),bd("0.23"),bd("0.27"),bd("0.18"),bd("0"),bd("0.59")},
        {bd("0.29"),bd("0.89"),bd("0.85"),bd("0.84"),null,bd("0.15"),bd("0.17"),bd("0.09"),bd("0.16"),bd("0.21"),bd("0.38"),bd("0.28"),bd("0.28"),bd("0.27"),bd("0.18"),bd("0"),bd("0.55")},
        {bd("0.21"),bd("0.21"),bd("0.12"),bd("0.14"),bd("0.15"),null,bd("0.33"),bd("0.53"),bd("0.26"),bd("0.09"),bd("0.21"),bd("0.04"),bd("0.11"),bd("0.1"),bd("0.09"),bd("0"),bd("0.24")},
        {bd("0.48"),bd("0.19"),bd("0.2"),bd("0.24"),bd("0.17"),bd("0.33"),null,bd("0.31"),bd("0.72"),bd("0.24"),bd("0.14"),bd("-0.12"),bd("0.19"),bd("0.14"),bd("0.08"),bd("0"),bd("0.24")},
        {bd("0.16"),bd("0.13"),bd("0.09"),bd("0.13"),bd("0.09"),bd("0.53"),bd("0.31"),null,bd("0.24"),bd("0.04"),bd("0.13"),bd("-0.07"),bd("0.04"),bd("0.06"),bd("0.01"),bd("0"),bd("0.16")},
        {bd("0.41"),bd("0.21"),bd("0.19"),bd("0.21"),bd("0.16"),bd("0.26"),bd("0.72"),bd("0.24"),null,bd("0.21"),bd("0.18"),bd("-0.07"),bd("0.12"),bd("0.12"),bd("0.1"),bd("0"),bd("0.21")},
        {bd("0.23"),bd("0.21"),bd("0.2"),bd("0.19"),bd("0.21"),bd("0.09"),bd("0.24"),bd("0.04"),bd("0.21"),null,bd("0.14"),bd("0.11"),bd("0.11"),bd("0.1"),bd("0.07"),bd("0"),bd("0.14")},
        {bd("0.18"),bd("0.41"),bd("0.36"),bd("0.39"),bd("0.38"),bd("0.21"),bd("0.14"),bd("0.13"),bd("0.18"),bd("0.14"),null,bd("0.28"),bd("0.3"),bd("0.25"),bd("0.18"),bd("0"),bd("0.38")},
        {bd("0.02"),bd("0.27"),bd("0.18"),bd("0.25"),bd("0.28"),bd("0.04"),bd("-0.12"),bd("-0.07"),bd("-0.07"),bd("0.11"),bd("0.28"),null,bd("0.18"),bd("0.18"),bd("0.08"),bd("0"),bd("0.21")},
        {bd("0.21"),bd("0.31"),bd("0.22"),bd("0.23"),bd("0.28"),bd("0.11"),bd("0.19"),bd("0.04"),bd("0.12"),bd("0.11"),bd("0.3"),bd("0.18"),null,bd("0.34"),bd("0.16"),bd("0"),bd("0.34")},
        {bd("0.19"),bd("0.29"),bd("0.23"),bd("0.27"),bd("0.27"),bd("0.1"),bd("0.14"),bd("0.06"),bd("0.12"),bd("0.1"),bd("0.25"),bd("0.18"),bd("0.34"),null,bd("0.13"),bd("0"),bd("0.26")},
        {bd("0.15"),bd("0.21"),bd("0.23"),bd("0.18"),bd("0.18"),bd("0.09"),bd("0.08"),bd("0.01"),bd("0.1"),bd("0.07"),bd("0.18"),bd("0.08"),bd("0.16"),bd("0.13"),null,bd("0"),bd("0.21")},
        {bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),bd("0"),null,bd("0")},
        {bd("0.24"),bd("0.6"),bd("0.54"),bd("0.59"),bd("0.55"),bd("0.24"),bd("0.24"),bd("0.16"),bd("0.21"),bd("0.14"),bd("0.38"),bd("0.21"),bd("0.34"),bd("0.26"),bd("0.21"),bd("0"),null}
    };

    // ===== BASE CORRELATION (1-day) =====
    static final BigDecimal BC_WEIGHT = bd("2.5");
    static final BigDecimal BC_CORR = bd("0.24");

    // ===== CROSS RISK CLASS (psi) =====
    // IR=0, FX=1, CRQ=2, CRNQ=3, EQ=4, CM=5
    static final BigDecimal[][] PSI = {
        {bd("1"),bd("0.32"),bd("0.29"),bd("0.13"),bd("0.28"),bd("0.41")},
        {bd("0.32"),bd("1"),bd("0.38"),bd("0.12"),bd("0.35"),bd("0.46")},
        {bd("0.29"),bd("0.38"),bd("1"),bd("0.54"),bd("0.71"),bd("0.52")},
        {bd("0.13"),bd("0.12"),bd("0.54"),bd("1"),bd("0.46"),bd("0.41")},
        {bd("0.28"),bd("0.35"),bd("0.71"),bd("0.46"),bd("1"),bd("0.49")},
        {bd("0.41"),bd("0.46"),bd("0.52"),bd("0.41"),bd("0.49"),bd("1")}
    };

    // ===== MAIN COMPUTATION =====

    static BigDecimal computeTotal(List<String[]> records) {
        Map<String, List<String[]>> byProduct = records.stream().collect(Collectors.groupingBy(r -> r[0]));
        BigDecimal total = BigDecimal.ZERO;
        for (List<String[]> precs : byProduct.values())
            total = total.add(computeProductMargin(precs));
        return total.setScale(0, RoundingMode.HALF_UP);
    }

    static BigDecimal computeProductMargin(List<String[]> records) {
        List<String[]> bcRecs = records.stream().filter(r -> r[1].equals(RT_BC)).collect(Collectors.toList());
        List<String[]> deltaRecs = records.stream().filter(r -> !r[1].equals(RT_BC)).collect(Collectors.toList());

        Map<Integer, List<String[]>> byRC = new HashMap<>();
        for (String[] r : deltaRecs)
            byRC.computeIfAbsent(rcIdx(r[1]), k -> new ArrayList<>()).add(r);

        BigDecimal[] m = new BigDecimal[6];
        Arrays.fill(m, BigDecimal.ZERO);
        for (Map.Entry<Integer, List<String[]>> e : byRC.entrySet())
            m[e.getKey()] = computeRC(e.getKey(), e.getValue());

        BigDecimal sq = BigDecimal.ZERO;
        for (int i = 0; i < 6; i++)
            for (int j = 0; j < 6; j++)
                sq = sq.add(PSI[i][j].multiply(m[i]).multiply(m[j]));

        return sqrt(sq).add(computeBaseCorr(bcRecs));
    }

    static int rcIdx(String rt) {
        switch (rt) {
            case RT_IR: case RT_INFLATION: case RT_XCCY: return 0;
            case RT_FX: return 1; case RT_CRQ: return 2; case RT_CRNQ: return 3;
            case RT_EQ: return 4; case RT_CM: return 5;
            default: throw new RuntimeException("Unknown: " + rt);
        }
    }

    static BigDecimal computeRC(int rc, List<String[]> recs) {
        switch (rc) {
            case 0: return irDelta(recs);
            case 1: return fxDelta(recs);
            case 2: return bucketedDelta(recs, "CRQ");
            case 3: return bucketedDelta(recs, "CRNQ");
            case 4: return bucketedDelta(recs, "EQ");
            case 5: return bucketedDelta(recs, "CM");
            default: return BigDecimal.ZERO;
        }
    }

    // ===== IR DELTA =====
    static BigDecimal irDelta(List<String[]> records) {
        Map<String, List<String[]>> byCcy = records.stream().collect(Collectors.groupingBy(r -> r[2]));
        List<BigDecimal> kVals = new ArrayList<>(), sVals = new ArrayList<>();

        for (Map.Entry<String, List<String[]>> entry : byCcy.entrySet()) {
            String ccy = entry.getKey();
            // Net by (riskType, tenor, subcurve)
            Map<String, BigDecimal> netByRF = new LinkedHashMap<>();
            Map<String, String[]> rfRep = new LinkedHashMap<>();
            for (String[] r : entry.getValue()) {
                String key = r[1] + "|" + r[4] + "|" + r[5];
                netByRF.merge(key, new BigDecimal(r[6]), BigDecimal::add);
                rfRep.putIfAbsent(key, r);
            }

            List<BigDecimal> ws = new ArrayList<>();
            List<String[]> reps = new ArrayList<>();
            for (Map.Entry<String, BigDecimal> e : netByRF.entrySet()) {
                String[] rep = rfRep.get(e.getKey());
                ws.add(irRW(ccy, rep[1], rep[4]).multiply(e.getValue()));
                reps.add(rep);
            }

            BigDecimal kSq = BigDecimal.ZERO;
            for (int i = 0; i < ws.size(); i++)
                for (int j = 0; j < ws.size(); j++) {
                    BigDecimal c = (i == j) ? BigDecimal.ONE : irCorr(reps.get(i), reps.get(j));
                    kSq = kSq.add(c.multiply(ws.get(i)).multiply(ws.get(j)));
                }
            BigDecimal k = sqrt(kSq.max(BigDecimal.ZERO));
            BigDecimal sumWS = ws.stream().reduce(BigDecimal.ZERO, BigDecimal::add);

            kVals.add(k);
            sVals.add(sumWS);
        }

        // Cross-currency aggregation
        BigDecimal res = BigDecimal.ZERO;
        for (int b = 0; b < kVals.size(); b++)
            res = res.add(kVals.get(b).multiply(kVals.get(b)));
        for (int b = 0; b < kVals.size(); b++)
            for (int c = 0; c < kVals.size(); c++)
                if (b != c)
                    res = res.add(IR_GAMMA.multiply(sVals.get(b)).multiply(sVals.get(c)));
        return sqrt(res.max(BigDecimal.ZERO));
    }

    static BigDecimal irRW(String ccy, String rt, String tenor) {
        if (rt.equals(RT_INFLATION)) return IR_INFLATION_RW;
        if (rt.equals(RT_XCCY)) return IR_XCCY_RW;
        int vol = IR_REGULAR.contains(ccy) ? 0 : IR_LOW_VOL.contains(ccy) ? 1 : 2;
        return IR_RW[vol][TENOR_IDX.getOrDefault(tenor, 0)];
    }

    static BigDecimal irCorr(String[] a, String[] b) {
        if (a[1].equals(RT_XCCY) || b[1].equals(RT_XCCY)) return IR_XCCY_CORR;
        if (a[1].equals(RT_INFLATION) || b[1].equals(RT_INFLATION)) return IR_INFLATION_CORR;
        BigDecimal c = IR_TENOR_CORR[TENOR_IDX.getOrDefault(a[4],0)][TENOR_IDX.getOrDefault(b[4],0)];
        if (!a[5].equals(b[5])) c = c.multiply(IR_SUB_CURVE_CORR);
        return c;
    }

    // ===== FX DELTA =====
    static BigDecimal fxDelta(List<String[]> records) {
        String calcCcy = "USD";
        Map<String, BigDecimal> net = new LinkedHashMap<>();
        for (String[] r : records) {
            if (r[2].equals(calcCcy)) continue; // exclude calculation currency
            net.merge(r[2], new BigDecimal(r[6]), BigDecimal::add);
        }

        List<String> ccys = new ArrayList<>(net.keySet());
        List<BigDecimal> ws = new ArrayList<>();
        for (String c : ccys) {
            int gv = FX_HIGH_VOL.contains(c) ? 1 : 0;
            int cv = FX_HIGH_VOL.contains(calcCcy) ? 1 : 0;
            ws.add(FX_RW[gv][cv].multiply(net.get(c)));
        }

        BigDecimal kSq = BigDecimal.ZERO;
        for (int i = 0; i < ws.size(); i++)
            for (int j = 0; j < ws.size(); j++) {
                BigDecimal corr = (i == j) ? BigDecimal.ONE : fxCorr(calcCcy, ccys.get(i), ccys.get(j));
                kSq = kSq.add(corr.multiply(ws.get(i)).multiply(ws.get(j)));
            }
        return sqrt(kSq.max(BigDecimal.ZERO));
    }

    static BigDecimal fxCorr(String calc, String c1, String c2) {
        int v1 = FX_HIGH_VOL.contains(c1) ? 1 : 0, v2 = FX_HIGH_VOL.contains(c2) ? 1 : 0;
        return FX_HIGH_VOL.contains(calc) ? FX_CORR_HIGH[v1][v2] : FX_CORR_REG[v1][v2];
    }

    // ===== BUCKETED DELTA (CRQ/CRNQ/EQ/CM) =====
    static BigDecimal bucketedDelta(List<String[]> records, String type) {
        Map<String, List<String[]>> byBkt = records.stream().collect(Collectors.groupingBy(r -> r[3]));
        List<String[]> resRecs = byBkt.getOrDefault("Residual", Collections.emptyList());
        Map<String, List<String[]>> nonRes = new LinkedHashMap<>(byBkt);
        nonRes.remove("Residual");

        List<Integer> bkts = new ArrayList<>();
        List<BigDecimal> kVals = new ArrayList<>(), sVals = new ArrayList<>();

        for (Map.Entry<String, List<String[]>> be : nonRes.entrySet()) {
            int bkt = Integer.parseInt(be.getKey());
            Map<String, BigDecimal> netRF = new LinkedHashMap<>();
            Map<String, String[]> rfRep = new LinkedHashMap<>();
            for (String[] r : be.getValue()) {
                String key = r[2] + "|" + r[4] + "|" + r[5];
                netRF.merge(key, new BigDecimal(r[6]), BigDecimal::add);
                rfRep.putIfAbsent(key, r);
            }

            BigDecimal rw = bktRW(type, bkt);
            List<BigDecimal> wsList = new ArrayList<>();
            List<String[]> reps = new ArrayList<>();
            for (Map.Entry<String, BigDecimal> e : netRF.entrySet()) {
                wsList.add(rw.multiply(e.getValue()));
                reps.add(rfRep.get(e.getKey()));
            }

            BigDecimal kSq = BigDecimal.ZERO;
            for (int i = 0; i < wsList.size(); i++)
                for (int j = 0; j < wsList.size(); j++)
                    kSq = kSq.add(((i==j)?BigDecimal.ONE:intraCorr(type,bkt,reps.get(i),reps.get(j))).multiply(wsList.get(i)).multiply(wsList.get(j)));
            BigDecimal k = sqrt(kSq.max(BigDecimal.ZERO));
            BigDecimal sumWS = wsList.stream().reduce(BigDecimal.ZERO, BigDecimal::add);

            bkts.add(bkt);
            kVals.add(k);
            sVals.add(sumWS);
        }

        // Residual
        BigDecimal resK = BigDecimal.ZERO;
        if (!resRecs.isEmpty()) {
            BigDecimal rw = resRW(type);
            Map<String, BigDecimal> netRF = new LinkedHashMap<>();
            Map<String, String[]> rfRep = new LinkedHashMap<>();
            for (String[] r : resRecs) {
                String key = r[2] + "|" + r[4] + "|" + r[5];
                netRF.merge(key, new BigDecimal(r[6]), BigDecimal::add);
                rfRep.putIfAbsent(key, r);
            }
            List<BigDecimal> wsList = new ArrayList<>();
            List<String[]> reps = new ArrayList<>();
            for (Map.Entry<String, BigDecimal> e : netRF.entrySet()) {
                wsList.add(rw.multiply(e.getValue()));
                reps.add(rfRep.get(e.getKey()));
            }
            BigDecimal kSq = BigDecimal.ZERO;
            for (int i = 0; i < wsList.size(); i++)
                for (int j = 0; j < wsList.size(); j++)
                    kSq = kSq.add(((i==j)?BigDecimal.ONE:resCorr(type)).multiply(wsList.get(i)).multiply(wsList.get(j)));
            resK = sqrt(kSq.max(BigDecimal.ZERO));
        }

        // Cross-bucket
        BigDecimal res = BigDecimal.ZERO;
        for (int b = 0; b < kVals.size(); b++)
            res = res.add(kVals.get(b).multiply(kVals.get(b)));
        for (int b = 0; b < kVals.size(); b++)
            for (int c = 0; c < kVals.size(); c++)
                if (b != c)
                    res = res.add(crossCorr(type, bkts.get(b), bkts.get(c)).multiply(sVals.get(b)).multiply(sVals.get(c)));
        return sqrt(res.max(BigDecimal.ZERO)).add(resK);
    }

    static BigDecimal intraCorr(String t, int bkt, String[] a, String[] b) {
        switch (t) {
            case "CRQ": return a[2].equals(b[2]) ? CRQ_SAME : CRQ_DIFF;
            case "CRNQ": return a[5].equals(b[5]) ? CRNQ_SAME : CRNQ_DIFF;
            case "EQ": return EQ_INTRA[bkt];
            case "CM": return CM_INTRA[bkt];
            default: return BigDecimal.ZERO;
        }
    }

    // ===== BASE CORRELATION =====
    static BigDecimal computeBaseCorr(List<String[]> records) {
        if (records.isEmpty()) return BigDecimal.ZERO;
        // Base correlation calculation is not yet implemented
        // TODO: implement base correlation margin
        return BigDecimal.ZERO;
    }

    // ===== PARAMETER LOOKUPS =====
    static BigDecimal bktRW(String t, int b) {
        switch (t) {
            case "CRQ": return CRQ_RW[b];
            case "CRNQ": return b==1?CRNQ_RW_1:CRNQ_RW_2;
            case "EQ": return EQ_RW[b];
            case "CM": return CM_RW[b];
            default: return bd("0");
        }
    }
    static BigDecimal resRW(String t) {
        switch (t) {
            case "CRQ": return CRQ_RW_RES;
            case "CRNQ": return CRNQ_RW_RES;
            case "EQ": return EQ_RW_RES;
            default: return bd("0");
        }
    }
    static BigDecimal resCorr(String t) {
        switch (t) {
            case "CRQ": return CRQ_RES;
            case "CRNQ": return CRNQ_RES;
            case "EQ": return BigDecimal.ZERO;
            default: return BigDecimal.ZERO;
        }
    }
    static BigDecimal crossCorr(String t, int b1, int b2) {
        switch (t) {
            case "CRQ": return CRQ_GAMMA[b1-1][b2-1];
            case "CRNQ": return CRNQ_GAMMA_VAL;
            case "EQ": return EQ_GAMMA[b1-1][b2-1];
            case "CM": return CM_GAMMA[b1-1][b2-1];
            default: return bd("0");
        }
    }

    static BigDecimal bd(String s) { return new BigDecimal(s); }
    static final BigDecimal TWO = BigDecimal.valueOf(2);
    static BigDecimal sqrt(BigDecimal v) {
        if (v.compareTo(BigDecimal.ZERO) <= 0) return BigDecimal.ZERO;
        BigDecimal x = new BigDecimal(Math.sqrt(v.doubleValue()), MC);
        // Newton's method for full BigDecimal precision
        for (int i = 0; i < 20; i++)
            x = v.divide(x, MC).add(x).divide(TWO, MC);
        return x;
    }
}
