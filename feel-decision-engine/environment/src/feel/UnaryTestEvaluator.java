package feel;

import java.util.ArrayList;
import java.util.List;

/**
 * Evaluates FEEL unary test expressions against input values.
 * Returns Boolean (true/false) or null for null-propagation per FEEL ternary logic.
 *
 */
public class UnaryTestEvaluator {

    /**
     * Evaluate a unary test expression against an input value.
     * @param expression The unary test (e.g., "> 10", "[1..100]", "not(\"X\")", "\"A\", \"B\"")
     * @param input The input value to test against
     * @return true if matches, false if not, null for null propagation
     */
    public static Boolean evaluate(String expression, FeelValue input) {
        expression = expression.trim();

        // Wildcard - matches any value including null
        if (expression.equals("-")) {
            return true;
        }

        // Handle disjunction (comma-separated tests at top level)
        List<String> disjuncts = splitDisjunction(expression);
        if (disjuncts.size() > 1) {
            return evaluateDisjunction(disjuncts, input);
        }

        // Handle negation: not(innerTest)
        if (expression.startsWith("not(") && expression.endsWith(")")) {
            String inner = expression.substring(4, expression.length() - 1);
            return evaluateNegation(inner, input);
        }

        // Handle range interval: [a..b], (a..b], [a..b), (a..b)
        if ((expression.startsWith("[") || expression.startsWith("(")) &&
            (expression.endsWith("]") || expression.endsWith(")"))) {
            String inner = expression.substring(1, expression.length() - 1);
            if (inner.contains("..")) {
                return evaluateRange(expression, input);
            }
        }

        // Handle comparison operators
        if (expression.startsWith("<=")) {
            return evaluateComparison("<=", expression.substring(2).trim(), input);
        }
        if (expression.startsWith(">=")) {
            return evaluateComparison(">=", expression.substring(2).trim(), input);
        }
        if (expression.startsWith("<")) {
            return evaluateComparison("<", expression.substring(1).trim(), input);
        }
        if (expression.startsWith(">")) {
            return evaluateComparison(">", expression.substring(1).trim(), input);
        }

        // Default: equality test
        return evaluateEquality(expression, input);
    }

    private static Boolean evaluateEquality(String expression, FeelValue input) {
        FeelValue testValue = FeelValue.parseLiteral(expression);

        if (testValue.isNull() && input.isNull()) return true;
        if (testValue.isNull() || input.isNull()) return false;

        return testValue.equals(input);
    }

    private static Boolean evaluateComparison(String op, String valueStr, FeelValue input) {
        FeelValue testValue = FeelValue.parseLiteral(valueStr);

        if (input.isNull()) return false;

        Integer cmp = input.compareTo(testValue);
        if (cmp == null) return false;

        switch (op) {
            case "<":  return cmp < 0;
            case "<=": return cmp <= 0;
            case ">":  return cmp > 0;
            case ">=": return cmp >= 0;
            default:   return false;
        }
    }

    private static Boolean evaluateRange(String expression, FeelValue input) {
        boolean lowerInclusive = expression.startsWith("[");
        boolean upperInclusive = expression.endsWith("]");

        String inner = expression.substring(1, expression.length() - 1);
        int dotDot = inner.indexOf("..");
        if (dotDot < 0) return null;

        String lowerStr = inner.substring(0, dotDot).trim();
        String upperStr = inner.substring(dotDot + 2).trim();

        FeelValue lower = FeelValue.parseLiteral(lowerStr);
        FeelValue upper = FeelValue.parseLiteral(upperStr);

        if (input.isNull()) return false;

        Integer cmpLower = input.compareTo(lower);
        Integer cmpUpper = input.compareTo(upper);

        if (cmpLower == null || cmpUpper == null) return null;

        // Check boundaries — use inclusivity flags to determine strict vs non-strict comparison
        boolean lowerOk = upperInclusive ? cmpLower >= 0 : cmpLower > 0;
        boolean upperOk = lowerInclusive ? cmpUpper <= 0 : cmpUpper < 0;

        return lowerOk && upperOk;
    }

    private static Boolean evaluateNegation(String inner, FeelValue input) {
        Boolean result = evaluate(inner, input);
        return result;
    }

    private static Boolean evaluateDisjunction(List<String> tests, FeelValue input) {
        Boolean result = true;
        for (String test : tests) {
            Boolean r = evaluate(test.trim(), input);
            if (r == null) {
                result = null;
            } else if (!r) {
                return false;
            }
        }
        return result;
    }

    /**
     * Split a unary test expression on top-level commas (outside parentheses/brackets/strings).
     */
    static List<String> splitDisjunction(String expression) {
        List<String> parts = new ArrayList<>();
        int depth = 0;
        int start = 0;
        boolean inString = false;

        for (int i = 0; i < expression.length(); i++) {
            char c = expression.charAt(i);
            if (c == '"' && (i == 0 || expression.charAt(i - 1) != '\\')) {
                inString = !inString;
            }
            if (!inString) {
                if (c == '(' || c == '[') depth++;
                if (c == ')' || c == ']') depth--;
                if (c == ',' && depth == 0) {
                    parts.add(expression.substring(start, i));
                    start = i + 1;
                }
            }
        }
        parts.add(expression.substring(start));
        return parts;
    }
}
