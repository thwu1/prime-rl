import java.util.*;


/**
 * Comprehensive test runner for the query plan optimizer.
 * Tests constant folding, boolean simplification, null propagation,
 * predicate pushdown, and their interactions through fixed-point iteration.
 */
public class TestRunner {
    private static int passed = 0, failed = 0;
    private static final Optimizer optimizer = new Optimizer();

    // Convenience: create a Scan for table t1 with non-nullable int columns a, b, c
    static Plan.Scan scanT1 = new Plan.Scan("t1", List.of(
        new Plan.Column("a", "int", false),
        new Plan.Column("b", "int", false),
        new Plan.Column("c", "int", false)
    ));
    // Scan for table t2 with non-nullable int columns a, b, c
    static Plan.Scan scanT2 = new Plan.Scan("t2", List.of(
        new Plan.Column("a", "int", false),
        new Plan.Column("b", "int", false),
        new Plan.Column("c", "int", false)
    ));

    // Attribute references (non-nullable)
    static Expr.AttributeRef t1a = new Expr.AttributeRef("t1", "a", "int", false);
    static Expr.AttributeRef t1b = new Expr.AttributeRef("t1", "b", "int", false);
    static Expr.AttributeRef t1c = new Expr.AttributeRef("t1", "c", "int", false);
    static Expr.AttributeRef t2a = new Expr.AttributeRef("t2", "a", "int", false);
    static Expr.AttributeRef t2b = new Expr.AttributeRef("t2", "b", "int", false);

    // Nullable attribute references
    static Expr.AttributeRef t1a_nullable = new Expr.AttributeRef("t1", "a", "int", true);

    // Common join condition: t1.b = t2.b
    static Expr joinCond = new Expr.Comparison(Expr.Comparison.Op.EQ, t1b, t2b);

    public static void main(String[] args) {
        testConstantFoldingBasic();
        testConstantFoldingNull();
        testConstantFoldingDivZero();
        testConstantFoldingChildPlan();
        testBooleanSimpAndTrue();
        testBooleanSimpAndFalse();
        testBooleanSimpOrFalse();
        testBooleanSimpNotNot();
        testBooleanSimpIdempotent();
        testBooleanSimpComplementNonnullable();
        testBooleanSimpComplementNullable();
        testBooleanSimpAbsorption();
        testBooleanSimpCommonFactor();
        testBooleanSimpDifferentOps();
        testNullPropNonnullableIsNull();
        testNullPropNonnullableIsNotNull();
        testNullPropNullableUnchanged();
        testNullPropNestedPlan();
        testPredicatePushdownBasic();
        testPredicatePushdownBothSides();
        testPredicatePushdownStacked();
        testCombinedAllRules();

        System.out.println("\nResults: " + passed + " passed, " + failed + " failed out of " + (passed + failed));
        System.exit(failed > 0 ? 1 : 0);
    }

    static void check(String testName, String expected, Plan result) {
        String actual = result.toCanonical();
        if (expected.equals(actual)) {
            System.out.println("PASS: " + testName);
            passed++;
        } else {
            System.out.println("FAIL: " + testName);
            System.out.println("  Expected: " + expected);
            System.out.println("  Actual:   " + actual);
            failed++;
        }
    }

    // =================== CONSTANT FOLDING ===================

    static void testConstantFoldingBasic() {
        // Filter(GT(t1.a, ADD(1, 2)), Scan(t1)) -> Filter(GT(t1.a, 3), Scan(t1))
        Expr cond = new Expr.Comparison(Expr.Comparison.Op.GT, t1a,
            new Expr.Arithmetic(Expr.Arithmetic.Op.ADD, Expr.Literal.ofInt(1), Expr.Literal.ofInt(2)));
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("constant_folding_basic",
            "Filter(GT(t1.a, 3), Scan(t1))", result);
    }

    static void testConstantFoldingNull() {
        // Filter(GT(t1.a, ADD(null:int, 5)), Scan(t1)) -> Filter(GT(t1.a, null:int), Scan(t1))
        Expr cond = new Expr.Comparison(Expr.Comparison.Op.GT, t1a,
            new Expr.Arithmetic(Expr.Arithmetic.Op.ADD, Expr.Literal.ofNull("int"), Expr.Literal.ofInt(5)));
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("constant_folding_null",
            "Filter(GT(t1.a, null:int), Scan(t1))", result);
    }

    static void testConstantFoldingDivZero() {
        // Filter(GT(t1.a, DIV(10, 0)), Scan(t1)) -> Filter(GT(t1.a, null:int), Scan(t1))
        Expr cond = new Expr.Comparison(Expr.Comparison.Op.GT, t1a,
            new Expr.Arithmetic(Expr.Arithmetic.Op.DIV, Expr.Literal.ofInt(10), Expr.Literal.ofInt(0)));
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("constant_folding_div_zero",
            "Filter(GT(t1.a, null:int), Scan(t1))", result);
    }

    static void testConstantFoldingChildPlan() {
        // Project([t1.a], Filter(GT(t1.b, ADD(3, 4)), Scan(t1)))
        // -> Project([t1.a], Filter(GT(t1.b, 7), Scan(t1)))
        Expr filterCond = new Expr.Comparison(Expr.Comparison.Op.GT, t1b,
            new Expr.Arithmetic(Expr.Arithmetic.Op.ADD, Expr.Literal.ofInt(3), Expr.Literal.ofInt(4)));
        Plan input = new Plan.Project(List.of(t1a), new Plan.Filter(filterCond, scanT1));
        Plan result = optimizer.optimize(input);
        check("constant_folding_child_plan",
            "Project([t1.a], Filter(GT(t1.b, 7), Scan(t1)))", result);
    }

    // =================== BOOLEAN SIMPLIFICATION ===================

    static void testBooleanSimpAndTrue() {
        // Filter(AND(GT(t1.a, 1), true), Scan(t1)) -> Filter(GT(t1.a, 1), Scan(t1))
        Expr cond = new Expr.And(
            new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1)),
            Expr.Literal.TRUE);
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("boolean_simp_and_true",
            "Filter(GT(t1.a, 1), Scan(t1))", result);
    }

    static void testBooleanSimpAndFalse() {
        // Filter(AND(GT(t1.a, 1), false), Scan(t1)) -> Filter(false, Scan(t1))
        Expr cond = new Expr.And(
            new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1)),
            Expr.Literal.FALSE);
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("boolean_simp_and_false",
            "Filter(false, Scan(t1))", result);
    }

    static void testBooleanSimpOrFalse() {
        // Filter(OR(GT(t1.a, 1), false), Scan(t1)) -> Filter(GT(t1.a, 1), Scan(t1))
        Expr cond = new Expr.Or(
            new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1)),
            Expr.Literal.FALSE);
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("boolean_simp_or_false",
            "Filter(GT(t1.a, 1), Scan(t1))", result);
    }

    static void testBooleanSimpNotNot() {
        // Filter(NOT(NOT(GT(t1.a, 1))), Scan(t1)) -> Filter(GT(t1.a, 1), Scan(t1))
        Expr inner = new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1));
        Expr cond = new Expr.Not(new Expr.Not(inner));
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("boolean_simp_not_not",
            "Filter(GT(t1.a, 1), Scan(t1))", result);
    }

    static void testBooleanSimpIdempotent() {
        // Filter(AND(GT(t1.a, 1), GT(t1.a, 1)), Scan(t1)) -> Filter(GT(t1.a, 1), Scan(t1))
        Expr pred = new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1));
        Expr pred2 = new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1));
        Expr cond = new Expr.And(pred, pred2);
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("boolean_simp_idempotent",
            "Filter(GT(t1.a, 1), Scan(t1))", result);
    }

    static void testBooleanSimpComplementNonnullable() {
        // Filter(AND(GT(t1.a, 1), NOT(GT(t1.a, 1))), Scan(t1)) -> Filter(false, Scan(t1))
        // This ONLY works because t1.a is non-nullable
        Expr pred = new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1));
        Expr pred2 = new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1));
        Expr cond = new Expr.And(pred, new Expr.Not(pred2));
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("boolean_simp_complement_nonnullable",
            "Filter(false, Scan(t1))", result);
    }

    static void testBooleanSimpComplementNullable() {
        // Filter(AND(GT(t1.a, 1), NOT(GT(t1.a, 1))), Scan(t1))
        // When t1.a IS nullable, complement must NOT be applied (SQL 3-valued logic)
        Expr pred = new Expr.Comparison(Expr.Comparison.Op.GT, t1a_nullable, Expr.Literal.ofInt(1));
        Expr pred2 = new Expr.Comparison(Expr.Comparison.Op.GT, t1a_nullable, Expr.Literal.ofInt(1));
        Expr cond = new Expr.And(pred, new Expr.Not(pred2));
        Plan scanNullable = new Plan.Scan("t1", List.of(
            new Plan.Column("a", "int", true),
            new Plan.Column("b", "int", false),
            new Plan.Column("c", "int", false)
        ));
        Plan input = new Plan.Filter(cond, scanNullable);
        Plan result = optimizer.optimize(input);
        check("boolean_simp_complement_nullable",
            "Filter(AND(GT(t1.a, 1), NOT(GT(t1.a, 1))), Scan(t1))", result);
    }

    static void testBooleanSimpAbsorption() {
        // Filter(AND(GT(t1.a, 1), OR(GT(t1.a, 1), GT(t1.b, 2))), Scan(t1))
        // -> Filter(GT(t1.a, 1), Scan(t1))   (absorption: a AND (a OR b) -> a)
        Expr a = new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1));
        Expr b = new Expr.Comparison(Expr.Comparison.Op.GT, t1b, Expr.Literal.ofInt(2));
        Expr a2 = new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1));
        Expr cond = new Expr.And(a, new Expr.Or(a2, b));
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("boolean_simp_absorption",
            "Filter(GT(t1.a, 1), Scan(t1))", result);
    }

    static void testBooleanSimpCommonFactor() {
        // (a AND b) OR (a AND c) -> a AND (b OR c)
        Expr a = new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1));
        Expr b = new Expr.Comparison(Expr.Comparison.Op.GT, t1b, Expr.Literal.ofInt(2));
        Expr c = new Expr.Comparison(Expr.Comparison.Op.GT, t1c, Expr.Literal.ofInt(3));
        Expr a2 = new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1));
        Expr cond = new Expr.Or(new Expr.And(a, b), new Expr.And(a2, c));
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("boolean_simp_common_factor",
            "Filter(AND(GT(t1.a, 1), OR(GT(t1.b, 2), GT(t1.c, 3))), Scan(t1))", result);
    }

    static void testBooleanSimpDifferentOps() {
        // Filter(AND(GT(t1.a, 1), LT(t1.a, 1)), Scan(t1))
        // Must NOT simplify via idempotence (GT != LT, even though children match)
        Expr gt = new Expr.Comparison(Expr.Comparison.Op.GT, t1a, Expr.Literal.ofInt(1));
        Expr lt = new Expr.Comparison(Expr.Comparison.Op.LT, t1a, Expr.Literal.ofInt(1));
        Expr cond = new Expr.And(gt, lt);
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("boolean_simp_different_ops",
            "Filter(AND(GT(t1.a, 1), LT(t1.a, 1)), Scan(t1))", result);
    }

    // =================== NULL PROPAGATION ===================

    static void testNullPropNonnullableIsNull() {
        // IsNull(t1.a) where t1.a is non-nullable -> false
        Expr cond = new Expr.IsNull(t1a);
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("null_prop_nonnullable_isnull",
            "Filter(false, Scan(t1))", result);
    }

    static void testNullPropNonnullableIsNotNull() {
        // IsNotNull(t1.a) where t1.a is non-nullable -> true
        Expr cond = new Expr.IsNotNull(t1a);
        Plan input = new Plan.Filter(cond, scanT1);
        Plan result = optimizer.optimize(input);
        check("null_prop_nonnullable_isnotnull",
            "Filter(true, Scan(t1))", result);
    }

    static void testNullPropNullableUnchanged() {
        // IsNull(t1.a) where t1.a IS nullable -> unchanged
        Plan scanNullable = new Plan.Scan("t1", List.of(
            new Plan.Column("a", "int", true),
            new Plan.Column("b", "int", false),
            new Plan.Column("c", "int", false)
        ));
        Expr cond = new Expr.IsNull(t1a_nullable);
        Plan input = new Plan.Filter(cond, scanNullable);
        Plan result = optimizer.optimize(input);
        check("null_prop_nullable_unchanged",
            "Filter(ISNULL(t1.a), Scan(t1))", result);
    }

    static void testNullPropNestedPlan() {
        // Project([t1.a], Filter(IsNotNull(t1.b), Scan(t1)))
        // -> Project([t1.a], Filter(true, Scan(t1)))
        Expr cond = new Expr.IsNotNull(t1b);
        Plan input = new Plan.Project(List.of(t1a), new Plan.Filter(cond, scanT1));
        Plan result = optimizer.optimize(input);
        check("null_prop_nested_plan",
            "Project([t1.a], Filter(true, Scan(t1)))", result);
    }

    // =================== PREDICATE PUSHDOWN ===================

    static void testPredicatePushdownBasic() {
        // Filter(EQ(t1.a, 1), Join(INNER, EQ(t1.b, t2.b), Scan(t1), Scan(t2)))
        // -> Join(INNER, EQ(t1.b, t2.b), Filter(EQ(t1.a, 1), Scan(t1)), Scan(t2))
        Expr pred = new Expr.Comparison(Expr.Comparison.Op.EQ, t1a, Expr.Literal.ofInt(1));
        Plan join = new Plan.Join("INNER", joinCond, scanT1, scanT2);
        Plan input = new Plan.Filter(pred, join);
        Plan result = optimizer.optimize(input);
        check("predicate_pushdown_basic",
            "Join(INNER, EQ(t1.b, t2.b), Filter(EQ(t1.a, 1), Scan(t1)), Scan(t2))", result);
    }

    static void testPredicatePushdownBothSides() {
        // Filter(AND(EQ(t1.a, 1), GT(t2.a, 5)), Join(INNER, EQ(t1.b, t2.b), Scan(t1), Scan(t2)))
        // -> Join(INNER, EQ(t1.b, t2.b), Filter(EQ(t1.a, 1), Scan(t1)), Filter(GT(t2.a, 5), Scan(t2)))
        Expr leftPred = new Expr.Comparison(Expr.Comparison.Op.EQ, t1a, Expr.Literal.ofInt(1));
        Expr rightPred = new Expr.Comparison(Expr.Comparison.Op.GT, t2a, Expr.Literal.ofInt(5));
        Expr cond = new Expr.And(leftPred, rightPred);
        Plan join = new Plan.Join("INNER", joinCond, scanT1, scanT2);
        Plan input = new Plan.Filter(cond, join);
        Plan result = optimizer.optimize(input);
        check("predicate_pushdown_both_sides",
            "Join(INNER, EQ(t1.b, t2.b), Filter(EQ(t1.a, 1), Scan(t1)), Filter(GT(t2.a, 5), Scan(t2)))", result);
    }

    static void testPredicatePushdownStacked() {
        // Two filters stacked above a join - both should be pushed down
        // Filter(EQ(t1.a, 1), Filter(GT(t2.a, 5), Join(INNER, ..., Scan(t1), Scan(t2))))
        // -> Join(INNER, ..., Filter(EQ(t1.a, 1), Scan(t1)), Filter(GT(t2.a, 5), Scan(t2)))
        // This requires multiple passes of PredicatePushdown (tests rule engine iteration)
        Expr pred1 = new Expr.Comparison(Expr.Comparison.Op.EQ, t1a, Expr.Literal.ofInt(1));
        Expr pred2 = new Expr.Comparison(Expr.Comparison.Op.GT, t2a, Expr.Literal.ofInt(5));
        Plan join = new Plan.Join("INNER", joinCond, scanT1, scanT2);
        Plan input = new Plan.Filter(pred1, new Plan.Filter(pred2, join));
        Plan result = optimizer.optimize(input);
        check("predicate_pushdown_stacked",
            "Join(INNER, EQ(t1.b, t2.b), Filter(EQ(t1.a, 1), Scan(t1)), Filter(GT(t2.a, 5), Scan(t2)))", result);
    }

    // =================== COMBINED ===================

    static void testCombinedAllRules() {
        // Complex plan requiring all four rules + fixed-point interaction:
        // Filter(AND(ISNOTNULL(t1.a), AND(GT(t1.a, ADD(1, 2)), AND(true, GT(t2.a, 5)))),
        //   Join(INNER, EQ(t1.b, t2.b), Scan(t1), Scan(t2)))
        //
        // Requires: CF, BS, NP, PP across multiple iterations to converge.
        Expr isNotNull = new Expr.IsNotNull(t1a);
        Expr leftPred = new Expr.Comparison(Expr.Comparison.Op.GT, t1a,
            new Expr.Arithmetic(Expr.Arithmetic.Op.ADD, Expr.Literal.ofInt(1), Expr.Literal.ofInt(2)));
        Expr rightPred = new Expr.And(Expr.Literal.TRUE,
            new Expr.Comparison(Expr.Comparison.Op.GT, t2a, Expr.Literal.ofInt(5)));
        Expr cond = new Expr.And(isNotNull, new Expr.And(leftPred, rightPred));
        Plan join = new Plan.Join("INNER", joinCond, scanT1, scanT2);
        Plan input = new Plan.Filter(cond, join);
        Plan result = optimizer.optimize(input);
        check("combined_all_rules",
            "Join(INNER, EQ(t1.b, t2.b), Filter(GT(t1.a, 3), Scan(t1)), Filter(GT(t2.a, 5), Scan(t2)))", result);
    }
}
