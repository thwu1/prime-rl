"""Memo structure for the Volcano/Cascades optimizer.

The memo (also called the MEMO table) stores equivalence classes of logical
plan expressions.  Each Group contains a set of logically equivalent
GroupExpressions.  During exploration, transformation rules add new equivalent
expressions; during implementation, the optimizer picks the cheapest physical
realisation for each group.
"""


class ExplorationMark:
    """Per-round explored/unexplored tracking."""
    def __init__(self):
        self._explored = {}

    def is_explored(self, round_num):
        return self._explored.get(round_num, False)

    def mark_explored(self, round_num):
        self._explored[round_num] = True

    def mark_unexplored(self, round_num):
        self._explored[round_num] = False


class GroupExpression:
    """A single logical plan node inside a Group, pointing to child Groups."""
    _id_counter = 0

    def __init__(self, plan, children=None):
        GroupExpression._id_counter += 1
        self.id = GroupExpression._id_counter
        self.plan = plan              # LogicalPlan
        self.children = children or []  # list[Group]
        self.exploration_mark = ExplorationMark()
        self.applied_transformations = set()  # set of rule-class names

    def __eq__(self, other):
        return isinstance(other, GroupExpression) and self.plan == other.plan \
               and self.children == other.children

    def __hash__(self):
        return hash(self.plan)


class GroupImplementation:
    """The chosen physical plan and its cost for a Group."""
    def __init__(self, physical_plan, cost, selected_expression):
        self.physical_plan = physical_plan
        self.cost = cost
        self.selected_expression = selected_expression


class Group:
    """An equivalence class of GroupExpressions that produce the same result."""
    _id_counter = 0

    def __init__(self, equivalents=None):
        Group._id_counter += 1
        self.id = Group._id_counter
        self.equivalents = equivalents or set()  # set[GroupExpression]
        self.exploration_mark = ExplorationMark()
        self.implementation = None  # GroupImplementation | None


class Memo:
    """Central memo structure mapping logical plans to groups."""
    def __init__(self):
        self.groups = {}          # id -> Group
        self.parents = {}         # group_expression_id -> Group
        self.expressions = {}     # LogicalPlan -> GroupExpression

    def get_or_create_expression(self, plan):
        if plan in self.expressions:
            return self.expressions[plan]
        child_groups = [self.get_or_create_group(c) for c in plan.children()]
        expr = GroupExpression(plan, child_groups)
        self.expressions[plan] = expr
        return expr

    def get_or_create_group(self, plan):
        expr = self.get_or_create_expression(plan)
        if expr.id in self.parents:
            group = self.parents[expr.id]
            group.equivalents.add(expr)
        else:
            group = Group({expr})
            self.groups[group.id] = group
        self.parents[expr.id] = group
        return group
