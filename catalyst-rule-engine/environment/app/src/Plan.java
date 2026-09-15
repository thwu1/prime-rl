import java.util.*;
import java.util.function.Function;
import java.util.stream.Collectors;


/**
 * Abstract base class for logical plan nodes.
 * Inspired by Apache Spark's Catalyst LogicalPlan hierarchy.
 */
public abstract class Plan {

    /** Child plan nodes. */
    public abstract List<Plan> planChildren();

    /** Create a copy with new children (same node type and expressions). */
    public abstract Plan withNewPlanChildren(List<Plan> newChildren);

    /** Expressions owned directly by this node (not by children). */
    public abstract List<Expr> nodeExpressions();

    /** Create a copy with expressions transformed by fn (this node only, NOT children). */
    public abstract Plan mapExpressions(Function<Expr, Expr> fn);

    /** The set of qualified attribute names produced by this plan node. */
    public abstract Set<String> outputAttributes();

    /**
     * Apply fn top-down to this plan tree: first to this node, then recursively to children.
     */
    public Plan transformDown(Function<Plan, Plan> fn) {
        Plan after = fn.apply(this);
        List<Plan> kids = after.planChildren();
        if (kids.isEmpty()) return after;
        List<Plan> newKids = new ArrayList<>();
        boolean changed = false;
        for (Plan k : kids) {
            Plan nk = k.transformDown(fn);
            newKids.add(nk);
            if (!nk.structuralEquals(k)) changed = true;
        }
        return changed ? after.withNewPlanChildren(newKids) : after;
    }

    /**
     * Transform all expressions in this plan tree using expr.transformDown(fn).
     * Should apply to this node AND recursively to all descendant plan nodes.
     */
    public Plan transformExpressions(Function<Expr, Expr> fn) {
        // Apply to this node's expressions
        Plan current = this.mapExpressions(fn);
        // NOTE: should also recurse into child plan nodes
        return current;
    }

    /** Structural equality of plan trees. */
    public boolean structuralEquals(Plan other) {
        if (other == null) return false;
        if (this == other) return true;
        if (!getClass().equals(other.getClass())) return false;
        if (!planNodeEquals(other)) return false;
        List<Expr> me = nodeExpressions(), oe = other.nodeExpressions();
        if (me.size() != oe.size()) return false;
        for (int i = 0; i < me.size(); i++)
            if (!me.get(i).structuralEquals(oe.get(i))) return false;
        List<Plan> mc = planChildren(), oc = other.planChildren();
        if (mc.size() != oc.size()) return false;
        for (int i = 0; i < mc.size(); i++)
            if (!mc.get(i).structuralEquals(oc.get(i))) return false;
        return true;
    }

    /** Node-level equality (fields other than expressions and children). */
    protected boolean planNodeEquals(Plan other) { return true; }

    @Override public String toString() { return toCanonical(); }
    public abstract String toCanonical();

    // ========================== Column metadata for Scan ==========================

    public static class Column {
        public final String name;
        public final String dataType;
        public final boolean nullable;

        public Column(String name, String dataType, boolean nullable) {
            this.name = name;
            this.dataType = dataType;
            this.nullable = nullable;
        }
    }

    // ========================== CONCRETE PLAN TYPES ==========================

    /** Table scan: a leaf node producing rows with named columns. */
    public static class Scan extends Plan {
        private final String tableName;
        private final List<Column> columns;

        public Scan(String tableName, List<Column> columns) {
            this.tableName = tableName;
            this.columns = columns;
        }

        public String getTableName() { return tableName; }
        public List<Column> getColumns() { return columns; }

        @Override public List<Plan> planChildren() { return Collections.emptyList(); }
        @Override public Plan withNewPlanChildren(List<Plan> c) { return this; }
        @Override public List<Expr> nodeExpressions() { return Collections.emptyList(); }
        @Override public Plan mapExpressions(Function<Expr, Expr> fn) { return this; }
        @Override public Set<String> outputAttributes() {
            Set<String> attrs = new LinkedHashSet<>();
            for (Column col : columns) attrs.add(tableName + "." + col.name);
            return attrs;
        }
        @Override protected boolean planNodeEquals(Plan other) {
            Scan s = (Scan) other;
            if (!tableName.equals(s.tableName)) return false;
            if (columns.size() != s.columns.size()) return false;
            for (int i = 0; i < columns.size(); i++) {
                Column a = columns.get(i), b = s.columns.get(i);
                if (!a.name.equals(b.name) || !a.dataType.equals(b.dataType) || a.nullable != b.nullable)
                    return false;
            }
            return true;
        }
        @Override public String toCanonical() { return "Scan(" + tableName + ")"; }
    }

    /** Filter: selects rows matching a boolean condition. */
    public static class Filter extends Plan {
        private final Expr condition;
        private final Plan child;

        public Filter(Expr condition, Plan child) {
            this.condition = condition;
            this.child = child;
        }

        public Expr getCondition() { return condition; }
        public Plan getChild() { return child; }

        @Override public List<Plan> planChildren() { return List.of(child); }
        @Override public Plan withNewPlanChildren(List<Plan> c) { return new Filter(condition, c.get(0)); }
        @Override public List<Expr> nodeExpressions() { return List.of(condition); }
        @Override public Plan mapExpressions(Function<Expr, Expr> fn) {
            Expr newCond = condition.transformDown(fn);
            return newCond.structuralEquals(condition) ? this : new Filter(newCond, child);
        }
        @Override public Set<String> outputAttributes() { return child.outputAttributes(); }
        @Override public String toCanonical() {
            return "Filter(" + condition.toCanonical() + ", " + child.toCanonical() + ")";
        }
    }

    /** Project: selects or computes a list of output expressions. */
    public static class Project extends Plan {
        private final List<Expr> expressions;
        private final Plan child;

        public Project(List<Expr> expressions, Plan child) {
            this.expressions = expressions;
            this.child = child;
        }

        public List<Expr> getExpressions() { return expressions; }
        public Plan getChild() { return child; }

        @Override public List<Plan> planChildren() { return List.of(child); }
        @Override public Plan withNewPlanChildren(List<Plan> c) { return new Project(expressions, c.get(0)); }
        @Override public List<Expr> nodeExpressions() { return expressions; }
        @Override public Plan mapExpressions(Function<Expr, Expr> fn) {
            List<Expr> newExprs = new ArrayList<>();
            boolean changed = false;
            for (Expr e : expressions) {
                Expr ne = e.transformDown(fn);
                newExprs.add(ne);
                if (!ne.structuralEquals(e)) changed = true;
            }
            return changed ? new Project(newExprs, child) : this;
        }
        @Override public Set<String> outputAttributes() {
            Set<String> attrs = new LinkedHashSet<>();
            for (Expr e : expressions) attrs.addAll(e.referencedAttributes());
            return attrs;
        }
        @Override public String toCanonical() {
            String exprs = expressions.stream().map(Expr::toCanonical).collect(Collectors.joining(", "));
            return "Project([" + exprs + "], " + child.toCanonical() + ")";
        }
    }

    /** Join: combines two plan inputs with a join condition. */
    public static class Join extends Plan {
        private final String joinType; // "INNER", "LEFT", "RIGHT", "FULL", "CROSS"
        private final Expr condition;  // may be null for CROSS join
        private final Plan left, right;

        public Join(String joinType, Expr condition, Plan left, Plan right) {
            this.joinType = joinType;
            this.condition = condition;
            this.left = left;
            this.right = right;
        }

        public String getJoinType() { return joinType; }
        public Expr getCondition() { return condition; }
        public Plan getLeft() { return left; }
        public Plan getRight() { return right; }

        @Override public List<Plan> planChildren() { return List.of(left, right); }
        @Override public Plan withNewPlanChildren(List<Plan> c) {
            return new Join(joinType, condition, c.get(0), c.get(1));
        }
        @Override public List<Expr> nodeExpressions() {
            return condition == null ? Collections.emptyList() : List.of(condition);
        }
        @Override public Plan mapExpressions(Function<Expr, Expr> fn) {
            if (condition == null) return this;
            Expr newCond = condition.transformDown(fn);
            return newCond.structuralEquals(condition) ? this : new Join(joinType, newCond, left, right);
        }
        @Override public Set<String> outputAttributes() {
            Set<String> attrs = new LinkedHashSet<>(left.outputAttributes());
            attrs.addAll(right.outputAttributes());
            return attrs;
        }
        @Override protected boolean planNodeEquals(Plan other) {
            return joinType.equals(((Join) other).joinType);
        }
        @Override public String toCanonical() {
            String condStr = condition == null ? "true" : condition.toCanonical();
            return "Join(" + joinType + ", " + condStr + ", " + left.toCanonical() + ", " + right.toCanonical() + ")";
        }
    }
}
