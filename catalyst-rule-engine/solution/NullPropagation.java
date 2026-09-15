
/**
 * Null propagation: simplifies IsNull/IsNotNull based on expression nullability metadata.
 */
public class NullPropagation implements Rule {
    @Override
    public Plan apply(Plan plan) {
        return plan.transformExpressions(expr -> {
            if (expr instanceof Expr.IsNull) {
                Expr child = ((Expr.IsNull) expr).getChild();
                if (!child.nullable()) {
                    return Expr.Literal.FALSE;
                }
            }
            if (expr instanceof Expr.IsNotNull) {
                Expr child = ((Expr.IsNotNull) expr).getChild();
                if (!child.nullable()) {
                    return Expr.Literal.TRUE;
                }
            }
            return expr;
        });
    }
}
