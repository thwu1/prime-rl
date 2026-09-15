
/**
 * A single optimization rule that transforms a logical plan.
 * Inspired by Apache Spark's Catalyst Rule[TreeType].
 */
public interface Rule {
    /** Apply this rule to the given plan, returning the (possibly transformed) result. */
    Plan apply(Plan plan);

    /** Name for logging/debugging. */
    default String name() { return getClass().getSimpleName(); }
}
