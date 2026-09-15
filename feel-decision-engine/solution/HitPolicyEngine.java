package feel;

import java.math.BigDecimal;
import java.util.*;

/**
 * Applies DMN hit policies to determine the output of a decision table evaluation.
 *
 */
public class HitPolicyEngine {

    public enum HitPolicy {
        UNIQUE, ANY, FIRST, PRIORITY, RULE_ORDER, COLLECT
    }

    public enum Aggregation {
        NONE, SUM, MIN, MAX, COUNT
    }

    /**
     * Apply hit policy to the list of matched rule outputs.
     */
    public static Object apply(HitPolicy policy, Aggregation aggregation,
                               List<Map<String, FeelValue>> matchedOutputs,
                               List<String> outputNames,
                               List<List<String>> outputValueLists) {

        if (matchedOutputs.isEmpty()) {
            return null;
        }

        switch (policy) {
            case UNIQUE:
                if (matchedOutputs.size() > 1) {
                    throw new RuntimeException(
                        "UNIQUE hit policy violated: " + matchedOutputs.size() + " rules matched");
                }
                return matchedOutputs.get(0);

            case ANY:
                Map<String, FeelValue> first = matchedOutputs.get(0);
                for (int i = 1; i < matchedOutputs.size(); i++) {
                    if (!first.equals(matchedOutputs.get(i))) {
                        throw new RuntimeException(
                            "ANY hit policy violated: matching rules have different outputs");
                    }
                }
                return first;

            case FIRST:
                return matchedOutputs.get(0);

            case PRIORITY:
                return applyPriority(matchedOutputs, outputNames, outputValueLists);

            case RULE_ORDER:
                return new ArrayList<>(matchedOutputs);

            case COLLECT:
                return applyCollect(aggregation, matchedOutputs, outputNames);

            default:
                throw new RuntimeException("Unknown hit policy: " + policy);
        }
    }

    private static Object applyPriority(List<Map<String, FeelValue>> matchedOutputs,
                                         List<String> outputNames,
                                         List<List<String>> outputValueLists) {
        String outputName = outputNames.get(0);
        List<String> priorityOrder = outputValueLists.get(0);

        Map<String, FeelValue> bestMatch = null;
        int bestPriority = Integer.MAX_VALUE;

        for (Map<String, FeelValue> output : matchedOutputs) {
            FeelValue v = output.get(outputName);
            String valStr = v != null ? v.toString() : "null";
            int priority = priorityOrder.indexOf(valStr);
            if (priority < 0) priority = Integer.MAX_VALUE;
            if (priority < bestPriority) {
                bestPriority = priority;
                bestMatch = output;
            }
        }

        return bestMatch;
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
                BigDecimal sum = BigDecimal.ZERO;
                for (Map<String, FeelValue> output : matchedOutputs) {
                    FeelValue v = output.get(outputName);
                    if (v != null && !v.isNull()) {
                        sum = sum.add(v.asNumber());
                    }
                }
                Map<String, FeelValue> result = new LinkedHashMap<>();
                result.put(outputName, FeelValue.of(sum));
                return result;
            }
            case MIN: {
                BigDecimal min = null;
                for (Map<String, FeelValue> output : matchedOutputs) {
                    FeelValue v = output.get(outputName);
                    if (v != null && !v.isNull()) {
                        BigDecimal n = v.asNumber();
                        if (min == null || n.compareTo(min) < 0) {
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
