import java.util.Collections;


/**
 * Constant folding optimization rule.
 * Should evaluate foldable, deterministic expressions at optimization time,
 * replacing them with their computed Literal values.
 *
 * Must handle: null propagation, division by zero, non-deterministic expressions.
 */
public class ConstantFolding implements Rule {
    @Override
    public Plan apply(Plan plan) {
        // TODO: implement constant folding
        return plan;
    }
}
