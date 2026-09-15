import java.util.*;
import java.util.function.Function;


/**
 * Abstract base class for all expressions in the query plan optimizer.
 * Inspired by Apache Spark's Catalyst expression hierarchy.
 */
public abstract class Expr {

    public abstract List<Expr> children();
    public abstract Expr withNewChildren(List<Expr> newChildren);
    public abstract String dataType();
    public abstract boolean nullable();
    public abstract Object evaluate(Map<String, Object> bindings);

    /** Whether this expression can be evaluated at compile time (all inputs are known constants). */
    public boolean foldable() { return false; }

    /** Whether this expression always produces the same result for the same inputs. */
    public boolean deterministic() { return children().stream().allMatch(Expr::deterministic); }

    /** Collect all qualified attribute names referenced by this expression. */
    public Set<String> referencedAttributes() {
        Set<String> refs = new HashSet<>();
        for (Expr c : children()) refs.addAll(c.referencedAttributes());
        return refs;
    }

    /**
     * Apply a transformation function top-down: first to this node, then recursively
     * to the children of the result.
     */
    public Expr transformDown(Function<Expr, Expr> fn) {
        Expr after = fn.apply(this);
        List<Expr> kids = after.children();
        if (kids.isEmpty()) return after;
        List<Expr> newKids = new ArrayList<>();
        boolean changed = false;
        for (Expr k : kids) {
            Expr nk = k.transformDown(fn);
            newKids.add(nk);
            if (!nk.structuralEquals(k)) changed = true;
        }
        return changed ? after.withNewChildren(newKids) : after;
    }

    /** Structural equality: same class, same node values, same children (recursively). */
    public boolean structuralEquals(Expr other) {
        if (other == null) return false;
        if (this == other) return true;
        if (!getClass().equals(other.getClass())) return false;
        if (!nodeEquals(other)) return false;
        List<Expr> mc = children(), oc = other.children();
        if (mc.size() != oc.size()) return false;
        for (int i = 0; i < mc.size(); i++)
            if (!mc.get(i).structuralEquals(oc.get(i))) return false;
        return true;
    }

    /** Node-level equality (fields other than children). Override in subclasses with value fields. */
    protected boolean nodeEquals(Expr other) { return true; }

    @Override public String toString() { return toCanonical(); }
    /** Canonical string representation for structural comparison. */
    public abstract String toCanonical();

    // ========================== CONCRETE EXPRESSION TYPES ==========================

    /** A constant literal value. Null is represented by value==null. */
    public static class Literal extends Expr {
        private final Object value;
        private final String dataType;

        public Literal(Object value, String dataType) {
            this.value = value;
            this.dataType = dataType;
        }

        public static Literal ofInt(int v) { return new Literal(v, "int"); }
        public static Literal ofLong(long v) { return new Literal(v, "long"); }
        public static Literal ofDouble(double v) { return new Literal(v, "double"); }
        public static Literal ofBoolean(boolean v) { return new Literal(v, "boolean"); }
        public static Literal ofNull(String dt) { return new Literal(null, dt); }
        public static final Literal TRUE = ofBoolean(true);
        public static final Literal FALSE = ofBoolean(false);

        public Object getValue() { return value; }
        @Override public List<Expr> children() { return Collections.emptyList(); }
        @Override public Expr withNewChildren(List<Expr> c) { return this; }
        @Override public boolean foldable() { return true; }
        @Override public boolean nullable() { return value == null; }
        @Override public String dataType() { return dataType; }
        @Override public Object evaluate(Map<String, Object> b) { return value; }
        @Override protected boolean nodeEquals(Expr o) {
            Literal l = (Literal) o;
            return Objects.equals(value, l.value) && dataType.equals(l.dataType);
        }
        @Override public String toCanonical() {
            if (value == null) return "null:" + dataType;
            return value.toString();
        }
    }

    /** A reference to a named column in a table. Carries its own nullability. */
    public static class AttributeRef extends Expr {
        private final String table;
        private final String column;
        private final String dataType;
        private final boolean isNullable;

        public AttributeRef(String table, String column, String dataType, boolean isNullable) {
            this.table = table;
            this.column = column;
            this.dataType = dataType;
            this.isNullable = isNullable;
        }

        public String getTable() { return table; }
        public String getColumn() { return column; }
        public String qualifiedName() { return table + "." + column; }

        @Override public List<Expr> children() { return Collections.emptyList(); }
        @Override public Expr withNewChildren(List<Expr> c) { return this; }
        @Override public boolean nullable() { return isNullable; }
        @Override public String dataType() { return dataType; }
        @Override public Object evaluate(Map<String, Object> b) { return b.get(qualifiedName()); }
        @Override public Set<String> referencedAttributes() {
            Set<String> s = new HashSet<>();
            s.add(qualifiedName());
            return s;
        }
        @Override protected boolean nodeEquals(Expr o) {
            AttributeRef a = (AttributeRef) o;
            return table.equals(a.table) && column.equals(a.column)
                && dataType.equals(a.dataType) && isNullable == a.isNullable;
        }
        @Override public String toCanonical() { return qualifiedName(); }
    }

    /** Binary arithmetic: ADD, SUB, MUL, DIV. */
    public static class Arithmetic extends Expr {
        public enum Op { ADD, SUB, MUL, DIV }
        private final Op op;
        private final Expr left, right;

        public Arithmetic(Op op, Expr left, Expr right) {
            this.op = op; this.left = left; this.right = right;
        }

        public Op getOp() { return op; }
        public Expr getLeft() { return left; }
        public Expr getRight() { return right; }

        @Override public List<Expr> children() { return List.of(left, right); }
        @Override public Expr withNewChildren(List<Expr> c) { return new Arithmetic(op, c.get(0), c.get(1)); }
        @Override public boolean foldable() { return left.foldable() && right.foldable(); }
        @Override public boolean nullable() { return left.nullable() || right.nullable(); }
        @Override public String dataType() { return promoteType(left.dataType(), right.dataType()); }
        @Override protected boolean nodeEquals(Expr o) {
            return this.op == ((Arithmetic) o).op;
        }
        @Override public Object evaluate(Map<String, Object> b) {
            Object lv = left.evaluate(b), rv = right.evaluate(b);
            if (lv == null || rv == null) return null;
            Number ln = (Number) lv, rn = (Number) rv;
            String dt = dataType();
            if (op == Op.DIV && rn.doubleValue() == 0.0) return null;
            switch (dt) {
                case "double": return evalDouble(ln.doubleValue(), rn.doubleValue());
                case "long":   return evalLong(ln.longValue(), rn.longValue());
                default:       return evalInt(ln.intValue(), rn.intValue());
            }
        }
        private Object evalDouble(double l, double r) {
            switch (op) { case ADD: return l+r; case SUB: return l-r; case MUL: return l*r; case DIV: return l/r; }
            throw new RuntimeException("unreachable");
        }
        private Object evalLong(long l, long r) {
            switch (op) { case ADD: return l+r; case SUB: return l-r; case MUL: return l*r; case DIV: return l/r; }
            throw new RuntimeException("unreachable");
        }
        private Object evalInt(int l, int r) {
            switch (op) { case ADD: return l+r; case SUB: return l-r; case MUL: return l*r; case DIV: return l/r; }
            throw new RuntimeException("unreachable");
        }
        @Override public String toCanonical() {
            return op.name() + "(" + left.toCanonical() + ", " + right.toCanonical() + ")";
        }
    }

    /** Binary comparison: EQ, NEQ, GT, GTE, LT, LTE. */
    public static class Comparison extends Expr {
        public enum Op { EQ, NEQ, GT, GTE, LT, LTE }
        private final Op op;
        private final Expr left, right;

        public Comparison(Op op, Expr left, Expr right) {
            this.op = op; this.left = left; this.right = right;
        }

        public Op getOp() { return op; }
        public Expr getLeft() { return left; }
        public Expr getRight() { return right; }

        @Override public List<Expr> children() { return List.of(left, right); }
        @Override public Expr withNewChildren(List<Expr> c) { return new Comparison(op, c.get(0), c.get(1)); }
        @Override public boolean foldable() { return left.foldable() && right.foldable(); }
        @Override public boolean nullable() { return left.nullable() || right.nullable(); }
        @Override public String dataType() { return "boolean"; }
        @Override protected boolean nodeEquals(Expr other) {
            return true;
        }
        @Override public Object evaluate(Map<String, Object> b) {
            Object lv = left.evaluate(b), rv = right.evaluate(b);
            if (lv == null || rv == null) return null;
            int cmp;
            if (lv instanceof Number && rv instanceof Number) {
                cmp = Double.compare(((Number) lv).doubleValue(), ((Number) rv).doubleValue());
            } else {
                @SuppressWarnings("unchecked")
                int c = ((Comparable<Object>) lv).compareTo(rv);
                cmp = c;
            }
            switch (op) {
                case EQ:  return cmp == 0;
                case NEQ: return cmp != 0;
                case GT:  return cmp > 0;
                case GTE: return cmp >= 0;
                case LT:  return cmp < 0;
                case LTE: return cmp <= 0;
            }
            throw new RuntimeException("unreachable");
        }
        @Override public String toCanonical() {
            return op.name() + "(" + left.toCanonical() + ", " + right.toCanonical() + ")";
        }
    }

    /** Boolean AND with SQL three-valued logic. */
    public static class And extends Expr {
        private final Expr left, right;
        public And(Expr left, Expr right) { this.left = left; this.right = right; }
        public Expr getLeft() { return left; }
        public Expr getRight() { return right; }
        @Override public List<Expr> children() { return List.of(left, right); }
        @Override public Expr withNewChildren(List<Expr> c) { return new And(c.get(0), c.get(1)); }
        @Override public boolean foldable() { return left.foldable() && right.foldable(); }
        @Override public boolean nullable() { return left.nullable() || right.nullable(); }
        @Override public String dataType() { return "boolean"; }
        @Override public Object evaluate(Map<String, Object> b) {
            Object lv = left.evaluate(b), rv = right.evaluate(b);
            if (Boolean.FALSE.equals(lv) || Boolean.FALSE.equals(rv)) return false;
            if (lv == null || rv == null) return null;
            return (Boolean) lv && (Boolean) rv;
        }
        @Override public String toCanonical() {
            return "AND(" + left.toCanonical() + ", " + right.toCanonical() + ")";
        }
    }

    /** Boolean OR with SQL three-valued logic. */
    public static class Or extends Expr {
        private final Expr left, right;
        public Or(Expr left, Expr right) { this.left = left; this.right = right; }
        public Expr getLeft() { return left; }
        public Expr getRight() { return right; }
        @Override public List<Expr> children() { return List.of(left, right); }
        @Override public Expr withNewChildren(List<Expr> c) { return new Or(c.get(0), c.get(1)); }
        @Override public boolean foldable() { return left.foldable() && right.foldable(); }
        @Override public boolean nullable() { return left.nullable() || right.nullable(); }
        @Override public String dataType() { return "boolean"; }
        @Override public Object evaluate(Map<String, Object> b) {
            Object lv = left.evaluate(b), rv = right.evaluate(b);
            if (Boolean.TRUE.equals(lv) || Boolean.TRUE.equals(rv)) return true;
            if (lv == null || rv == null) return null;
            return (Boolean) lv || (Boolean) rv;
        }
        @Override public String toCanonical() {
            return "OR(" + left.toCanonical() + ", " + right.toCanonical() + ")";
        }
    }

    /** Boolean NOT with SQL three-valued logic. */
    public static class Not extends Expr {
        private final Expr child;
        public Not(Expr child) { this.child = child; }
        public Expr getChild() { return child; }
        @Override public List<Expr> children() { return List.of(child); }
        @Override public Expr withNewChildren(List<Expr> c) { return new Not(c.get(0)); }
        @Override public boolean foldable() { return child.foldable(); }
        @Override public boolean nullable() { return child.nullable(); }
        @Override public String dataType() { return "boolean"; }
        @Override public Object evaluate(Map<String, Object> b) {
            Object v = child.evaluate(b);
            if (v == null) return null;
            return !(Boolean) v;
        }
        @Override public String toCanonical() { return "NOT(" + child.toCanonical() + ")"; }
    }

    /** IS NULL check. Always non-nullable (returns true or false, never null). */
    public static class IsNull extends Expr {
        private final Expr child;
        public IsNull(Expr child) { this.child = child; }
        public Expr getChild() { return child; }
        @Override public List<Expr> children() { return List.of(child); }
        @Override public Expr withNewChildren(List<Expr> c) { return new IsNull(c.get(0)); }
        @Override public boolean foldable() { return child.foldable(); }
        @Override public boolean nullable() { return false; }
        @Override public String dataType() { return "boolean"; }
        @Override public Object evaluate(Map<String, Object> b) {
            return child.evaluate(b) == null;
        }
        @Override public String toCanonical() { return "ISNULL(" + child.toCanonical() + ")"; }
    }

    /** IS NOT NULL check. Always non-nullable. */
    public static class IsNotNull extends Expr {
        private final Expr child;
        public IsNotNull(Expr child) { this.child = child; }
        public Expr getChild() { return child; }
        @Override public List<Expr> children() { return List.of(child); }
        @Override public Expr withNewChildren(List<Expr> c) { return new IsNotNull(c.get(0)); }
        @Override public boolean foldable() { return child.foldable(); }
        @Override public boolean nullable() { return false; }
        @Override public String dataType() { return "boolean"; }
        @Override public Object evaluate(Map<String, Object> b) {
            return child.evaluate(b) != null;
        }
        @Override public String toCanonical() { return "ISNOTNULL(" + child.toCanonical() + ")"; }
    }

    // ========================== HELPERS ==========================

    static String promoteType(String a, String b) {
        if ("double".equals(a) || "double".equals(b)) return "double";
        if ("long".equals(a) || "long".equals(b)) return "long";
        return "int";
    }
}
