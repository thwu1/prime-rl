package feel;

import java.math.BigDecimal;
import java.util.*;

/**
 * Applies DMN hit policies to determine the output of a decision table evaluation.
 *
 */
public class HitPolicyEngine {

    public enum HitPolicy {
        UNIQUE, ANY, FIRST, RULE_ORDER, COLLECT
    }

    public enum Aggregation {
        NONE, SUM, MIN, MAX, COUNT
    }

    /**
     * Apply hit policy to the list of matched rule outputs.
     *
     * @param policy       The hit policy to apply
     * @param aggregation  The aggregation type (for COLLECT policy)
     * @param matchedOutputs  List of output maps from rules that matched, in rule definition order
     * @param outputNames  Names of output columns (for aggregation targeting)
     * @return A single Map (single-result), List of Maps (multi-result), or throws RuntimeException for violations
     */
    public static Object apply(HitPolicy policy, Aggregation aggregation,
                               List<Map<String, FeelValue>> matchedOutputs,
                               List<String> outputNames) {

        if (matchedOutputs.isEmpty()) {
            return null;
        }

        switch (policy) {
            case UNIQUE:
                return matchedOutputs.get(0);

            case ANY:
                return matchedOutputs.get(0);

            case FIRST:
                return matchedOutputs.get(0);

            case RULE_ORDER:
                List<Map<String, FeelValue>> ordered = new ArrayList<>(matchedOutputs);
                Collections.reverse(ordered);
                return ordered;

            case COLLECT:
                return applyCollect(aggregation, matchedOutputs, outputNames);

            default:
                throw new RuntimeException("Unknown hit policy: " + policy);
        }
    }

    private static Object applyCollect(Aggregation aggregation,
                                        List<Map<String, FeelValue>> matchedOutputs,
                                        List<String> outputNames) {
        if (aggregation == Aggregation.NONE) {
            return new ArrayList<>(matchedOutputs);
        }

        String outputName = outputNames.get(0);

        switch (aggregation) {
            case SUM: {
                int sum = 0;
                for (Map<String, FeelValue> output : matchedOutputs) {
                    FeelValue v = output.get(outputName);
                    if (v != null && !v.isNull()) {
                        sum += v.asNumber().intValue();
                    }
                }
                Map<String, FeelValue> result = new LinkedHashMap<>();
                result.put(outputName, FeelValue.of(BigDecimal.valueOf(sum)));
                return result;
            }
            case MIN: {
                BigDecimal min = null;
                for (Map<String, FeelValue> output : matchedOutputs) {
                    FeelValue v = output.get(outputName);
                    if (v != null && !v.isNull()) {
                        BigDecimal n = v.asNumber();
                        if (min == null || n.compareTo(min) > 0) {
                            min = n;
                        }
                    }
                }
                Map<String, FeelValue> result = new LinkedHashMap<>();
                result.put(outputName, min != null ? FeelValue.of(min) : FeelValue.ofNull());
                return result;
            }
            case MAX: {
                BigDecimal max = null;
                for (Map<String, FeelValue> output : matchedOutputs) {
                    FeelValue v = output.get(outputName);
                    if (v != null && !v.isNull()) {
                        BigDecimal n = v.asNumber();
                        if (max == null || n.compareTo(max) > 0) {
                            max = n;
                        }
                    }
                }
                Map<String, FeelValue> result = new LinkedHashMap<>();
                result.put(outputName, max != null ? FeelValue.of(max) : FeelValue.ofNull());
                return result;
            }
            case COUNT: {
                int count = matchedOutputs.size();
                Map<String, FeelValue> result = new LinkedHashMap<>();
                result.put(outputName, FeelValue.of(BigDecimal.valueOf(count)));
                return result;
            }
            default:
                return new ArrayList<>(matchedOutputs);
        }
    }
}
