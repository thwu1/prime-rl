"""Core types for the Volcano/Cascades cost-based query optimizer."""

from dataclasses import dataclass, field
from typing import Any


# ─── AST / Identifier Types ─────────────────────────────────────────────────

@dataclass(frozen=True)
class TableID:
    name: str

@dataclass(frozen=True)
class FieldID:
    table: TableID
    name: str
    def fqn(self):
        return f"{self.table.name}.{self.name}"

@dataclass(frozen=True)
class FilterCondition:
    field: FieldID
    op: str   # '=', '<', '>', '<=', '>=', '!='
    value: Any


# ─── Logical Plan Types ─────────────────────────────────────────────────────

class LogicalPlan:
    """Base class for logical plan nodes in the optimizer's search space."""
    def children(self):
        return []
    def describe(self):
        raise NotImplementedError
    def collect_tables(self):
        """Return set of all table names referenced in this subtree."""
        result = set()
        for c in self.children():
            result |= c.collect_tables()
        return result


class LPScan(LogicalPlan):
    """Logical scan of a single table, optionally with column projection."""
    def __init__(self, table, projection=None):
        self.table = table          # TableID
        self.projection = projection or []  # list of column name strings
    def describe(self):
        if self.projection:
            return f"SCAN {self.table.name} ({', '.join(self.projection)})"
        return f"SCAN {self.table.name}"
    def collect_tables(self):
        return {self.table.name}
    def __eq__(self, other):
        return isinstance(other, LPScan) and self.table == other.table and \
               sorted(self.projection) == sorted(other.projection)
    def __hash__(self):
        return hash(("scan", self.table, tuple(sorted(self.projection))))


class LPProject(LogicalPlan):
    """Logical projection selecting specific output fields."""
    def __init__(self, fields, child):
        self.fields = fields  # list of FieldID
        self.child = child    # LogicalPlan
    def children(self):
        return [self.child]
    def describe(self):
        return f"PROJECT {', '.join(f.fqn() for f in self.fields)}"
    def collect_tables(self):
        return self.child.collect_tables()
    def __eq__(self, other):
        return isinstance(other, LPProject) and \
               sorted(self.fields, key=lambda f: f.fqn()) == \
               sorted(other.fields, key=lambda f: f.fqn()) and \
               self.child == other.child
    def __hash__(self):
        return hash(("project", tuple(sorted(f.fqn() for f in self.fields)), self.child))


class LPJoin(LogicalPlan):
    """Logical equi-join of two children on specified field pairs."""
    def __init__(self, left, right, on):
        self.left = left    # LogicalPlan
        self.right = right  # LogicalPlan
        self.on = on        # list of (FieldID, FieldID) tuples
    def children(self):
        return [self.left, self.right]
    def describe(self):
        return "JOIN"
    def collect_tables(self):
        return self.left.collect_tables() | self.right.collect_tables()
    def __eq__(self, other):
        if not isinstance(other, LPJoin):
            return False
        return (self.left == other.left and self.right == other.right) or \
               (self.left == other.right and self.right == other.left)
    def __hash__(self):
        return hash(("join", frozenset([hash(self.left), hash(self.right)])))


class LPFilter(LogicalPlan):
    """Logical filter applying one or more predicates."""
    def __init__(self, conditions, child):
        self.conditions = conditions  # list of FilterCondition
        self.child = child            # LogicalPlan
    def children(self):
        return [self.child]
    def describe(self):
        conds = ' AND '.join(f"{c.field.fqn()} {c.op} {c.value}" for c in self.conditions)
        return f"FILTER ({conds})"
    def collect_tables(self):
        return self.child.collect_tables()
    def __eq__(self, other):
        return isinstance(other, LPFilter) and self.conditions == other.conditions \
               and self.child == other.child
    def __hash__(self):
        return hash(("filter", tuple(self.conditions), self.child))


# ─── Table Statistics & Catalog ──────────────────────────────────────────────

@dataclass
class TableStats:
    estimated_row_count: int
    avg_column_sizes: dict   # column_name -> avg_size_bytes

    @property
    def avg_row_size(self):
        return sum(self.avg_column_sizes.values())

    @property
    def estimated_table_size(self):
        return self.estimated_row_count * self.avg_row_size

@dataclass
class TableCatalog:
    columns: list   # list of (name, type_str) tuples
    metadata: dict = field(default_factory=dict)

    @property
    def column_names(self):
        return [c[0] for c in self.columns]


# ─── Cost & Estimations ─────────────────────────────────────────────────────

@dataclass
class Cost:
    cpu: float
    memory: float
    time: float
    def __repr__(self):
        return f"Cost(cpu={self.cpu:.1f}, mem={self.memory:.1f}, time={self.time:.1f})"

@dataclass
class Estimations:
    loop_iterations: int
    row_size: int


# ─── Physical Plan ───────────────────────────────────────────────────────────

class PhysicalPlan:
    """A concrete physical execution plan node with cost and estimations."""
    def __init__(self, plan_type, cost, estimations, traits=None, children=None):
        self.plan_type = plan_type
        self._cost = cost
        self._estimations = estimations
        self._traits = traits or set()
        self._children = children or []

    def cost(self):
        return self._cost
    def estimations(self):
        return self._estimations
    def traits(self):
        return self._traits
    def children(self):
        return self._children
    def describe_tree(self, indent=0):
        lines = ["  " * indent + f"{self.plan_type} {self._cost}"]
        for c in self._children:
            lines.append(c.describe_tree(indent + 1))
        return "\n".join(lines)
