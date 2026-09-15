package feel;

import java.math.BigDecimal;
import java.util.*;

/**
 * Orchestrates decision table evaluation: coerces input types,
 * evaluates rules, and delegates to HitPolicyEngine.
 *
 */
public class DecisionTableEngine {

    @SuppressWarnings("unchecked")
    public static Object evaluate(Map<String, Object> tableDef, Map<String, Object> inputData) {
        String hitPolicyStr = (String) tableDef.get("hitPolicy");
        String aggregationStr = (String) tableDef.getOrDefault("aggregation", "NONE");

        HitPolicyEngine.HitPolicy hitPolicy = HitPolicyEngine.HitPolicy.valueOf(hitPolicyStr);
        HitPolicyEngine.Aggregation aggregation = HitPolicyEngine.Aggregation.valueOf(aggregationStr);

        List<Map<String, Object>> inputs = (List<Map<String, Object>>) tableDef.get("inputs");
        List<Map<String, Object>> outputs = (List<Map<String, Object>>) tableDef.get("outputs");
        List<Map<String, Object>> rules = (List<Map<String, Object>>) tableDef.get("rules");

        // Convert input data to FeelValues based on declared column types
        List<FeelValue> inputValues = new ArrayList<>();
        for (Map<String, Object> inputCol : inputs) {
            String name = (String) inputCol.get("name");
            String type = (String) inputCol.get("type");
            Object jsonValue = inputData.get(name);
            inputValues.add(coerceInput(jsonValue, type));
        }

        // Evaluate each rule against the input values
        List<Map<String, FeelValue>> matchedOutputs = new ArrayList<>();
        for (Map<String, Object> rule : rules) {
            List<String> inputEntries = (List<String>) rule.get("inputs");
            List<String> outputEntries = (List<String>) rule.get("outputs");

            // A rule matches only if ALL input entries match (ternary AND)
            Boolean ruleMatch = true;
            for (int i = 0; i < inputEntries.size(); i++) {
                Boolean entryMatch = UnaryTestEvaluator.evaluate(inputEntries.get(i), inputValues.get(i));
                ruleMatch = feelAnd(ruleMatch, entryMatch);
            }

            if (Boolean.TRUE.equals(ruleMatch)) {
                Map<String, FeelValue> outputMap = new LinkedHashMap<>();
                for (int i = 0; i < outputs.size(); i++) {
                    String outputName = (String) outputs.get(i).get("name");
                    String outputEntry = outputEntries.get(i);
                    outputMap.put(outputName, FeelValue.parseLiteral(outputEntry));
                }
                matchedOutputs.add(outputMap);
            }
        }

        // Extract output column names and output-value orderings for hit policy
        List<String> outputNames = new ArrayList<>();
        List<List<String>> outputValueLists = new ArrayList<>();
        for (Map<String, Object> output : outputs) {
            outputNames.add((String) output.get("name"));
            List<String> vals = (List<String>) output.get("outputValues");
            outputValueLists.add(vals != null ? vals : Collections.emptyList());
        }

        return HitPolicyEngine.apply(hitPolicy, aggregation, matchedOutputs, outputNames, outputValueLists);
    }

    /**
     * FEEL ternary AND: false dominates null, null dominates true.
     */
    static Boolean feelAnd(Boolean a, Boolean b) {
        if (Boolean.FALSE.equals(a) || Boolean.FALSE.equals(b)) return false;
        if (a == null || b == null) return null;
        return a && b;
    }

    /**
     * Coerce a JSON value to a FeelValue based on declared column type.
     */
    static FeelValue coerceInput(Object jsonValue, String type) {
        if (jsonValue == null) return FeelValue.ofNull();
        switch (type) {
            case "number":
                if (jsonValue instanceof BigDecimal) return FeelValue.of((BigDecimal) jsonValue);
                return FeelValue.of(new BigDecimal(jsonValue.toString()));
            case "string":
                return FeelValue.of(jsonValue.toString());
            case "boolean":
                if (jsonValue instanceof Boolean) return FeelValue.of((Boolean) jsonValue);
                return FeelValue.of(Boolean.parseBoolean(jsonValue.toString()));
            case "date":
                return FeelValue.of(java.time.LocalDate.parse(jsonValue.toString()));
            default:
                return FeelValue.fromJson(jsonValue);
        }
    }
}
