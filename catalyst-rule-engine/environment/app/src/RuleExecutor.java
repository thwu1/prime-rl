import java.util.*;


/**
 * Executes batches of optimization rules against a logical plan.
 * Supports ONCE (single pass) and FIXED_POINT (iterate until convergence) strategies.
 * Inspired by Apache Spark's Catalyst RuleExecutor.
 */
public class RuleExecutor {

    public enum Strategy { ONCE, FIXED_POINT }

    public static class Batch {
        public final String name;
        public final Strategy strategy;
        public final int maxIterations;
        public final List<Rule> rules;

        public Batch(String name, Strategy strategy, int maxIterations, Rule... rules) {
            this.name = name;
            this.strategy = strategy;
            this.maxIterations = maxIterations;
            this.rules = List.of(rules);
        }
    }

    private final List<Batch> batches;

    public RuleExecutor(List<Batch> batches) {
        this.batches = batches;
    }

    /**
     * Execute all batches on the given plan.
     * For FIXED_POINT batches, rules should be applied iteratively until the plan
     * stabilizes or maxIterations is reached.
     */
    public Plan execute(Plan plan) {
        Plan current = plan;
        for (Batch batch : batches) {
            for (Rule rule : batch.rules) {
                current = rule.apply(current);
            }
        }
        return current;
    }
}
