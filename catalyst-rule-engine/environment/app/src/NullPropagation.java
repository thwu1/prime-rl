
/**
 * Null propagation optimization rule.
 * Should simplify IsNull and IsNotNull expressions based on nullability metadata.
 */
public class NullPropagation implements Rule {
    @Override
    public Plan apply(Plan plan) {
        // TODO: implement null propagation
        return plan;
    }
}
