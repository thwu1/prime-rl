#!/usr/bin/env python3
"""Fix infrastructure bugs in the optimizer codebase."""


import sys

# ============================================================
# Bug 1: Plan.transformExpressions doesn't recurse into children
# ============================================================
with open('/app/src/Plan.java', 'r') as f:
    plan_code = f.read()

old_transform = """    public Plan transformExpressions(Function<Expr, Expr> fn) {
        // Apply to this node's expressions
        Plan current = this.mapExpressions(fn);
        // NOTE: should also recurse into child plan nodes
        return current;
    }"""

new_transform = """    public Plan transformExpressions(Function<Expr, Expr> fn) {
        Plan current = this.mapExpressions(fn);
        List<Plan> kids = current.planChildren();
        if (kids.isEmpty()) return current;
        List<Plan> newKids = new ArrayList<>();
        boolean changed = false;
        for (Plan k : kids) {
            Plan nk = k.transformExpressions(fn);
            newKids.add(nk);
            if (!nk.structuralEquals(k)) changed = true;
        }
        return changed ? current.withNewPlanChildren(newKids) : current;
    }"""

if old_transform not in plan_code:
    print("ERROR: Bug 1 pattern not found in Plan.java", file=sys.stderr)
    sys.exit(1)
plan_code = plan_code.replace(old_transform, new_transform)

with open('/app/src/Plan.java', 'w') as f:
    f.write(plan_code)

print("Fixed Bug 1: Plan.transformExpressions now recurses into children")

# ============================================================
# Bug 2: RuleExecutor doesn't iterate for FIXED_POINT strategy
# ============================================================
with open('/app/src/RuleExecutor.java', 'r') as f:
    executor_code = f.read()

old_execute = """    public Plan execute(Plan plan) {
        Plan current = plan;
        for (Batch batch : batches) {
            for (Rule rule : batch.rules) {
                current = rule.apply(current);
            }
        }
        return current;
    }"""

new_execute = """    public Plan execute(Plan plan) {
        Plan current = plan;
        for (Batch batch : batches) {
            if (batch.strategy == Strategy.ONCE) {
                for (Rule rule : batch.rules) {
                    current = rule.apply(current);
                }
            } else {
                // FIXED_POINT: iterate until convergence or maxIterations
                for (int iter = 0; iter < batch.maxIterations; iter++) {
                    Plan lastPlan = current;
                    for (Rule rule : batch.rules) {
                        current = rule.apply(current);
                    }
                    if (current.structuralEquals(lastPlan)) break;
                }
            }
        }
        return current;
    }"""

if old_execute not in executor_code:
    print("ERROR: Bug 2 pattern not found in RuleExecutor.java", file=sys.stderr)
    sys.exit(1)
executor_code = executor_code.replace(old_execute, new_execute)

with open('/app/src/RuleExecutor.java', 'w') as f:
    f.write(executor_code)

print("Fixed Bug 2: RuleExecutor now iterates for FIXED_POINT batches")

# ============================================================
# Bug 3: Comparison.nodeEquals doesn't compare the op field
# ============================================================
with open('/app/src/Expr.java', 'r') as f:
    expr_code = f.read()

old_comparison_equals = """        @Override protected boolean nodeEquals(Expr other) {
            return true;
        }
        @Override public Object evaluate"""

new_comparison_equals = """        @Override protected boolean nodeEquals(Expr other) {
            return this.op == ((Comparison) other).op;
        }
        @Override public Object evaluate"""

if old_comparison_equals not in expr_code:
    print("ERROR: Bug 3 pattern not found in Expr.java", file=sys.stderr)
    sys.exit(1)
expr_code = expr_code.replace(old_comparison_equals, new_comparison_equals)

with open('/app/src/Expr.java', 'w') as f:
    f.write(expr_code)

print("Fixed Bug 3: Comparison.nodeEquals now compares op field")

# ============================================================
# Bug 4: ConfigLoader case-sensitive strategy comparison
# ============================================================
with open('/app/src/ConfigLoader.java', 'r') as f:
    config_code = f.read()

old_strategy = '"fixed_point".equals(strategyStr)'
new_strategy = '"fixed_point".equalsIgnoreCase(strategyStr)'

if old_strategy not in config_code:
    print("ERROR: Bug 4 pattern not found in ConfigLoader.java", file=sys.stderr)
    sys.exit(1)
config_code = config_code.replace(old_strategy, new_strategy)

with open('/app/src/ConfigLoader.java', 'w') as f:
    f.write(config_code)

print("Fixed Bug 4: ConfigLoader now uses case-insensitive strategy comparison")

# ============================================================
# Bug 5: Makefile test target runs java from wrong directory
# ============================================================
with open('/app/Makefile', 'r') as f:
    makefile = f.read()

old_test = 'cd $(BUILD_DIR) && $(JAVA) -cp . TestRunner'
new_test = '$(JAVA) -cp $(BUILD_DIR) TestRunner'

if old_test not in makefile:
    print("ERROR: Bug 5 pattern not found in Makefile", file=sys.stderr)
    sys.exit(1)
makefile = makefile.replace(old_test, new_test)

with open('/app/Makefile', 'w') as f:
    f.write(makefile)

print("Fixed Bug 5: Makefile test target now runs from correct directory")
