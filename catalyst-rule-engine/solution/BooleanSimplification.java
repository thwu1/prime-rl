
/**
 * Boolean simplification rule respecting SQL three-valued NULL logic.
 */
public class BooleanSimplification implements Rule {
    @Override
    public Plan apply(Plan plan) {
        return plan.transformExpressions(this::simplify);
    }

    private Expr simplify(Expr expr) {
        if (expr instanceof Expr.And) {
            Expr.And and = (Expr.And) expr;
            Expr l = and.getLeft(), r = and.getRight();

            // AND with FALSE -> FALSE
            if (isFalse(l) || isFalse(r)) return Expr.Literal.FALSE;
            // AND with TRUE -> other side
            if (isTrue(r)) return l;
            if (isTrue(l)) return r;
            // Idempotence: a AND a -> a
            if (l.structuralEquals(r)) return l;
            // Complement (non-nullable only): a AND NOT(a) -> FALSE
            if (!l.nullable() && r instanceof Expr.Not
                    && ((Expr.Not) r).getChild().structuralEquals(l)) return Expr.Literal.FALSE;
            if (!r.nullable() && l instanceof Expr.Not
                    && ((Expr.Not) l).getChild().structuralEquals(r)) return Expr.Literal.FALSE;
            // Absorption: a AND (a OR b) -> a
            if (r instanceof Expr.Or) {
                Expr.Or or = (Expr.Or) r;
                if (or.getLeft().structuralEquals(l) || or.getRight().structuralEquals(l)) return l;
            }
            if (l instanceof Expr.Or) {
                Expr.Or or = (Expr.Or) l;
                if (or.getLeft().structuralEquals(r) || or.getRight().structuralEquals(r)) return r;
            }
        }

        if (expr instanceof Expr.Or) {
            Expr.Or or = (Expr.Or) expr;
            Expr l = or.getLeft(), r = or.getRight();

            // OR with TRUE -> TRUE
            if (isTrue(l) || isTrue(r)) return Expr.Literal.TRUE;
            // OR with FALSE -> other side
            if (isFalse(r)) return l;
            if (isFalse(l)) return r;
            // Idempotence: a OR a -> a
            if (l.structuralEquals(r)) return l;
            // Complement (non-nullable only): a OR NOT(a) -> TRUE
            if (!l.nullable() && r instanceof Expr.Not
                    && ((Expr.Not) r).getChild().structuralEquals(l)) return Expr.Literal.TRUE;
            if (!r.nullable() && l instanceof Expr.Not
                    && ((Expr.Not) l).getChild().structuralEquals(r)) return Expr.Literal.TRUE;
            // Absorption: a OR (a AND b) -> a
            if (r instanceof Expr.And) {
                Expr.And and = (Expr.And) r;
                if (and.getLeft().structuralEquals(l) || and.getRight().structuralEquals(l)) return l;
            }
            if (l instanceof Expr.And) {
                Expr.And and = (Expr.And) l;
                if (and.getLeft().structuralEquals(r) || and.getRight().structuralEquals(r)) return r;
            }
            // Common factor: (a AND b) OR (a AND c) -> a AND (b OR c)
            if (l instanceof Expr.And && r instanceof Expr.And) {
                Expr.And la = (Expr.And) l, ra = (Expr.And) r;
                if (la.getLeft().structuralEquals(ra.getLeft())) {
                    return new Expr.And(la.getLeft(), new Expr.Or(la.getRight(), ra.getRight()));
                }
                if (la.getLeft().structuralEquals(ra.getRight())) {
                    return new Expr.And(la.getLeft(), new Expr.Or(la.getRight(), ra.getLeft()));
                }
                if (la.getRight().structuralEquals(ra.getLeft())) {
                    return new Expr.And(la.getRight(), new Expr.Or(la.getLeft(), ra.getRight()));
                }
                if (la.getRight().structuralEquals(ra.getRight())) {
                    return new Expr.And(la.getRight(), new Expr.Or(la.getLeft(), ra.getLeft()));
                }
            }
        }

        if (expr instanceof Expr.Not) {
            Expr.Not not = (Expr.Not) expr;
            Expr child = not.getChild();
            // Double negation: NOT(NOT(x)) -> x
            if (child instanceof Expr.Not) {
                return ((Expr.Not) child).getChild();
            }
        }

        return expr;
    }

    private static boolean isTrue(Expr e) {
        return e instanceof Expr.Literal && Boolean.TRUE.equals(((Expr.Literal) e).getValue());
    }

    private static boolean isFalse(Expr e) {
        return e instanceof Expr.Literal && Boolean.FALSE.equals(((Expr.Literal) e).getValue());
    }
}
