import java.util.Collections;


/**
 * Constant folding: evaluates foldable, deterministic expressions at optimization time.
 * Handles null propagation and division by zero (produces null, doesn't crash).
 */
public class ConstantFolding implements Rule {
    @Override
    public Plan apply(Plan plan) {
        return plan.transformExpressions(expr -> {
            if (expr.foldable() && expr.deterministic() && !(expr instanceof Expr.Literal)) {
                try {
                    Object result = expr.evaluate(Collections.emptyMap());
                    return new Expr.Literal(result, expr.dataType());
                } catch (Exception e) {
                    // If evaluation fails (e.g. unexpected error), produce null
                    return new Expr.Literal(null, expr.dataType());
                }
            }
            return expr;
        });
    }
}
