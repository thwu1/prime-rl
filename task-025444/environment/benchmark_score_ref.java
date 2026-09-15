/**
 *
 * Excerpt from org.owasp.benchmarkutils.score.BenchmarkScore
 *
 * This is the authoritative reference implementation for the OWASP Benchmark
 * scoring methodology. Key methods:
 *   - compare()          : Determines if a tool correctly identified a vulnerability
 *   - calculateScores()  : Counts TP/FN/FP/TN per vulnerability category
 *   - calculateMetrics() : Computes per-category rates and macro-averaged overall metrics
 */

// ============================================================================
// Supporting types (simplified for reference)
// ============================================================================

class TestCaseResult {
    private int number;      // Test case number
    private int CWE;         // CWE identifier
    private boolean truePositive; // true = real vulnerability, false = false positive test
    private boolean passed;  // Whether the tool's response was correct

    public int getCWE() { return CWE; }
    public boolean isTruePositive() { return truePositive; }
    public boolean isPassed() { return passed; }
    public void setPassed(boolean passed) { this.passed = passed; }
}

class TP_FN_TN_FP_Counts {
    public int tp, fn, tn, fp;
}

// ============================================================================
// compare() — CWE matching with exception handling
// ============================================================================

/**
 * Determine whether a tool correctly identified or dismissed a test case.
 *
 * A tool may report zero, one, or multiple findings per test case. Each finding
 * has a CWE number. We iterate through all findings to check for a CWE match.
 *
 * @param exp     Expected test case result (ground truth: CWE + true/false positive label)
 * @param actList List of actual findings from the tool for this test case
 * @param tool    Tool name (used for CWE exception prefix matching)
 * @return true if the tool's result is correct for this test case
 */
private static boolean compare(TestCaseResult exp, List<TestCaseResult> actList, String tool) {

    // If tool reported no findings for this test case
    if (actList == null || actList.isEmpty()) {
        // Correct only if the test is a false positive (no real vulnerability to find)
        return !exp.isTruePositive();
    }

    // Check each finding to see if any CWE matches the expected CWE
    for (TestCaseResult act : actList) {
        int actualCWE = act.getCWE();
        int expectedCWE = exp.getCWE();
        boolean match = (actualCWE == expectedCWE);

        // CWE Exception: Hibernate Query Language Injection (CWE 564)
        // Many tools report this as SQL Injection (CWE 89) instead.
        // Accept CWE 89 as a match when CWE 564 is expected.
        if (!match && (expectedCWE == 564)) {
            match = (actualCWE == 89);
        }

        // CWE Exception: Weak Algorithm (CWE 327 vs CWE 328)
        // Some tools (AppScan, Veracode, CodeQL) don't distinguish between
        // CWE-327 (Broken Crypto Algorithm) and CWE-328 (Reversible One-Way Hash).
        // When CWE-328 is expected, accept CWE-327 for these specific tools.
        //
        // NOTE: Uses tool.startsWith() for prefix matching — "AppScanSource",
        // "AppScanDynamic", etc. all match the "AppScan" prefix.
        if (!match) {
            if (tool.startsWith("AppScan") || tool.startsWith("Vera") || tool.startsWith("CodeQL")) {
                if (expectedCWE == 328 && actualCWE == 327) {
                    match = true;
                }
            }
        }

        if (match) {
            // A finding with matching CWE exists:
            //   True positive test  → tool found the real vulnerability → CORRECT
            //   False positive test → tool falsely reported a finding   → INCORRECT
            return exp.isTruePositive();
        }
    }

    // No matching CWE found among any findings:
    //   True positive test  → tool missed the vulnerability      → INCORRECT
    //   False positive test → tool correctly didn't flag this     → CORRECT
    return !exp.isTruePositive();
}


// ============================================================================
// calculateScores() — Count TP/FN/FP/TN per vulnerability category
// ============================================================================

/**
 * Classify each test case result and count outcomes per vulnerability category.
 *
 * The "passed" flag on each test case has already been set by compare().
 * This method groups results by category and counts the four outcome types.
 */
private static Map<String, TP_FN_TN_FP_Counts> calculateScores(TestSuiteResults actualResults) {
    Map<String, TP_FN_TN_FP_Counts> scores = new TreeMap<>();

    for (int tc : actualResults.keySet()) {
        TestCaseResult tcr = actualResults.get(tc).get(0);
        String category = Categories.getById(tcr.getCWE()).getName();
        TP_FN_TN_FP_Counts c = scores.computeIfAbsent(category, k -> new TP_FN_TN_FP_Counts());

        // Classification logic:
        //   truePositive && passed  → TP (tool found real vuln)
        //   truePositive && !passed → FN (tool missed real vuln)
        //  !truePositive && passed  → TN (tool correctly ignored non-vuln)
        //  !truePositive && !passed → FP (tool falsely flagged non-vuln)
        if (tcr.isTruePositive() && tcr.isPassed()) {
            c.tp++;
        } else if (tcr.isTruePositive() && !tcr.isPassed()) {
            c.fn++;
        } else if (!tcr.isTruePositive() && tcr.isPassed()) {
            c.tn++;
        } else { // !truePositive && !passed
            c.fp++;
        }
    }
    return scores;
}


// ============================================================================
// calculateMetrics() — Per-category rates + MACRO-AVERAGED overall metrics
// ============================================================================

/**
 * Compute per-category TPR and FPR, then macro-average across categories
 * for overall metrics.
 *
 * IMPORTANT: This uses MACRO-AVERAGING — the arithmetic mean of per-category
 * rates. Each vulnerability category contributes equally to the overall score,
 * regardless of how many test cases it contains. This differs from micro-averaging
 * which would weight by test case count.
 *
 * Overall score = Youden's J statistic = macro_TPR - macro_FPR
 */
private static ToolResults calculateMetrics(Map<String, TP_FN_TN_FP_Counts> results) {
    ToolResults metrics = new ToolResults();

    double totalTPRate = 0;
    double totalFPRate = 0;
    int totalTP = 0, totalFP = 0, totalFN = 0, totalTN = 0;
    int resultsSize = results.size();  // number of vulnerability categories

    for (Map.Entry<String, TP_FN_TN_FP_Counts> entry : results.entrySet()) {
        String category = entry.getKey();
        TP_FN_TN_FP_Counts c = entry.getValue();

        double precision = (double) c.tp / (double) (c.tp + c.fp);
        if (Double.isNaN(precision)) precision = 0;

        // Per-category True Positive Rate (sensitivity/recall)
        double tpr = (double) c.tp / (double) (c.tp + c.fn);
        if (Double.isNaN(tpr)) tpr = 0;

        // Per-category False Positive Rate
        double fpr = (double) c.fp / (double) (c.fp + c.tn);
        if (Double.isNaN(fpr)) fpr = 0;

        // Accumulate per-category rates for MACRO-averaging
        totalTPRate += tpr;
        totalFPRate += fpr;

        totalTP += c.tp;
        totalFP += c.fp;
        totalFN += c.fn;
        totalTN += c.tn;

        int rowTotal = c.tp + c.fn + c.fp + c.tn;
        metrics.add(category, precision, tpr, fpr, rowTotal);
    }

    // MACRO-AVERAGED overall rates: mean of per-category rates
    // (NOT micro-averaged from total counts)
    metrics.setTruePositiveRate(totalTPRate / resultsSize);
    metrics.setFalsePositiveRate(totalFPRate / resultsSize);

    // Overall precision uses total counts (not macro-averaged)
    double totalPrecision = (double) totalTP / (double) (totalTP + totalFP);
    if (Double.isNaN(totalPrecision)) totalPrecision = 0;
    metrics.setPrecision(totalPrecision);

    return metrics;
}


// ============================================================================
// Youden's J statistic — used for ranking tools
// ============================================================================
//
// J = TPR - FPR  (using macro-averaged rates)
//
// Range: -1 to +1
//   +1 = perfect classification
//    0 = no better than random guessing
//   -1 = perfectly wrong (worse than random)
//
// Tools are ranked by descending Youden's J.
