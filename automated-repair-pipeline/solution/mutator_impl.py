"""AST-based mutation operators for automated program repair."""

import ast
import copy
import random
from typing import Dict, List, Optional, Set, Tuple


def collect_local_names(func_def: ast.FunctionDef) -> Set[str]:
    """Collect parameter names and locally assigned variable names."""
    names: Set[str] = set()
    for arg in func_def.args.args:
        names.add(arg.arg)
    for node in ast.walk(func_def):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
    return names


def collect_statements(node: ast.AST) -> List[ast.stmt]:
    """Recursively collect all leaf-level statements in a function body."""
    stmts: List[ast.stmt] = []
    for attr in ('body', 'orelse', 'finalbody', 'handlers'):
        items = getattr(node, attr, None)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, ast.stmt):
                    stmts.append(item)
                    stmts.extend(collect_statements(item))
    return stmts


def _replace_in_tree(node: ast.AST, old: ast.AST, new: ast.AST) -> bool:
    """Replace `old` with `new` in the AST rooted at `node`. Returns True on success."""
    for attr in ('body', 'orelse', 'finalbody', 'handlers'):
        items = getattr(node, attr, None)
        if isinstance(items, list):
            for i, item in enumerate(items):
                if item is old:
                    items[i] = new
                    return True
                if isinstance(item, ast.stmt) and _replace_in_tree(item, old, new):
                    return True
    return False


class StatementMutator:
    """Mutate AST statements guided by suspiciousness scores."""

    def __init__(self,
                 suspiciousness: Optional[Dict[Tuple[str, int], float]] = None,
                 func_name: str = ''):
        self.suspiciousness = suspiciousness or {}
        self.func_name = func_name

    def mutate(self, tree: ast.AST) -> ast.AST:
        """Produce a mutated copy of `tree`."""
        tree = copy.deepcopy(tree)

        func_def = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == self.func_name:
                func_def = node
                break
        if func_def is None:
            # Fallback: take the first FunctionDef
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_def = node
                    break
        if func_def is None:
            return tree

        stmts = collect_statements(func_def)
        if not stmts:
            return tree

        local_names = collect_local_names(func_def)

        # Weight by suspiciousness
        weights = []
        for stmt in stmts:
            lineno = getattr(stmt, 'lineno', 0)
            s = self.suspiciousness.get((self.func_name, lineno), 0.01)
            weights.append(max(s, 0.01))

        target = random.choices(stmts, weights=weights, k=1)[0]

        # Choose mutation type — bias toward swap_name which fixes variable bugs
        op = random.choices(
            ['swap_name', 'swap_stmt', 'delete'],
            weights=[5, 3, 2],
            k=1
        )[0]

        if op == 'swap_name':
            self._swap_name(target, local_names)
        elif op == 'swap_stmt':
            self._swap_stmt(func_def, target, stmts)
        else:
            self._delete_stmt(func_def, target)

        ast.fix_missing_locations(tree)
        return tree

    def _swap_name(self, stmt: ast.AST, names: Set[str]) -> None:
        """Replace a random Name node in the statement with another local name."""
        name_nodes = [n for n in ast.walk(stmt)
                      if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)]
        if not name_nodes:
            return
        target_node = random.choice(name_nodes)
        candidates = [n for n in names if n != target_node.id]
        if candidates:
            target_node.id = random.choice(list(candidates))

    def _swap_stmt(self, func_def: ast.FunctionDef, target: ast.stmt,
                   source_stmts: List[ast.stmt]) -> None:
        """Replace target statement with another from the source pool."""
        donor = copy.deepcopy(random.choice(source_stmts))
        # Strip compound statement bodies to avoid deep nesting
        if isinstance(donor, (ast.If, ast.For, ast.While)):
            donor.body = [ast.Pass()]
            if hasattr(donor, 'orelse'):
                donor.orelse = []
        ast.copy_location(donor, target)
        _replace_in_tree(func_def, target, donor)

    def _delete_stmt(self, func_def: ast.FunctionDef, target: ast.stmt) -> None:
        """Replace target statement with pass."""
        new_node = ast.Pass()
        ast.copy_location(new_node, target)
        _replace_in_tree(func_def, target, new_node)
