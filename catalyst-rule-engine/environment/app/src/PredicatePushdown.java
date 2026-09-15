
/**
 * Predicate pushdown optimization rule.
 * Should push filter predicates through joins to reduce the amount of data
 * processed by the join operator.
 *
 * For Filter above Join:
 *   - Decompose AND conjuncts in the filter condition
 *   - Push predicates referencing only left-side attributes to the left child
 *   - Push predicates referencing only right-side attributes to the right child
 *   - Keep predicates referencing both sides above the join
 *   - Do not push non-deterministic predicates
 */
public class PredicatePushdown implements Rule {
    @Override
    public Plan apply(Plan plan) {
        // TODO: implement predicate pushdown
        return plan;
    }
}
