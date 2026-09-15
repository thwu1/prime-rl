import java.util.*;


/**
 * Predicate pushdown: pushes filter predicates through joins to reduce data volume.
 */
public class PredicatePushdown implements Rule {
    @Override
    public Plan apply(Plan plan) {
        return plan.transformDown(this::pushDown);
    }

    private Plan pushDown(Plan p) {
        if (!(p instanceof Plan.Filter)) return p;
        Plan.Filter filter = (Plan.Filter) p;
        if (!(filter.getChild() instanceof Plan.Join)) return p;

        Plan.Join join = (Plan.Join) filter.getChild();
        Set<String> leftAttrs = join.getLeft().outputAttributes();
        Set<String> rightAttrs = join.getRight().outputAttributes();

        List<Expr> conjuncts = flattenAnd(filter.getCondition());
        List<Expr> leftPreds = new ArrayList<>();
        List<Expr> rightPreds = new ArrayList<>();
        List<Expr> remainPreds = new ArrayList<>();

        for (Expr pred : conjuncts) {
            if (!pred.deterministic()) {
                remainPreds.add(pred);
                continue;
            }
            Set<String> refs = pred.referencedAttributes();
            if (leftAttrs.containsAll(refs)) {
                leftPreds.add(pred);
            } else if (rightAttrs.containsAll(refs)) {
                rightPreds.add(pred);
            } else {
                remainPreds.add(pred);
            }
        }

        // If nothing can be pushed, return unchanged
        if (leftPreds.isEmpty() && rightPreds.isEmpty()) return p;

        Plan newLeft = leftPreds.isEmpty() ? join.getLeft()
            : new Plan.Filter(combineAnd(leftPreds), join.getLeft());
        Plan newRight = rightPreds.isEmpty() ? join.getRight()
            : new Plan.Filter(combineAnd(rightPreds), join.getRight());

        Plan newJoin = new Plan.Join(join.getJoinType(), join.getCondition(), newLeft, newRight);

        if (remainPreds.isEmpty()) return newJoin;
        return new Plan.Filter(combineAnd(remainPreds), newJoin);
    }

    /** Flatten nested AND expressions into a list of conjuncts. */
    private static List<Expr> flattenAnd(Expr expr) {
        List<Expr> result = new ArrayList<>();
        if (expr instanceof Expr.And) {
            Expr.And and = (Expr.And) expr;
            result.addAll(flattenAnd(and.getLeft()));
            result.addAll(flattenAnd(and.getRight()));
        } else {
            result.add(expr);
        }
        return result;
    }

    /** Combine a list of expressions with AND. */
    private static Expr combineAnd(List<Expr> exprs) {
        Expr result = exprs.get(0);
        for (int i = 1; i < exprs.size(); i++) {
            result = new Expr.And(result, exprs.get(i));
        }
        return result;
    }
}
