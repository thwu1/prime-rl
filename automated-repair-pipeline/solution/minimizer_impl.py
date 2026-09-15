"""Delta debugging minimizer for repair simplification."""

import ast
from typing import Any, Callable, List, Sequence, Tuple

PASS = 'PASS'
FAIL = 'FAIL'
UNRESOLVED = 'UNRESOLVED'


def ddmin(test: Callable, inp: List, *test_args: Any) -> List:
    """Reduce `inp` to a 1-minimal failing subset using delta debugging.

    `test(candidate, *test_args)` must return PASS, FAIL, or UNRESOLVED.
    """
    assert test(inp, *test_args) != PASS

    n = 2
    while len(inp) >= 2:
        start = 0
        subset_length = max(len(inp) // n, 1)
        some_complement_failing = False

        while start < len(inp):
            complement = inp[:start] + inp[start + subset_length:]

            result = test(complement, *test_args)
            if result == FAIL:
                inp = complement
                n = max(n - 1, 2)
                some_complement_failing = True
                break

            start += subset_length

        if not some_complement_failing:
            if n == len(inp):
                break
            n = min(n * 2, len(inp))

    return inp


class DeltaDebugMinimizer:
    """Minimize a repaired program using delta debugging on source lines."""

    def __init__(self, func_name: str):
        self.func_name = func_name

    def minimize(self, repaired_tree: ast.AST,
                 test_cases: List[Tuple[tuple, Any]]) -> ast.AST:
        """Attempt to minimize the repair by removing unnecessary lines."""
        from .repairer import compute_fitness

        source = ast.unparse(repaired_tree)
        lines = source.split('\n')

        func_name = self.func_name

        def test_lines(candidate_lines: List[str], *args: Any) -> str:
            code = '\n'.join(candidate_lines)
            try:
                tree = ast.parse(code)
                fitness = compute_fitness(tree, test_cases, func_name)
                if fitness >= 1.0:
                    return FAIL  # "Fail" means repair still works -> keep reducing
                return PASS    # "Pass" means repair broken -> line was needed
            except (SyntaxError, ValueError, TypeError):
                return UNRESOLVED

        if test_lines(lines) != FAIL:
            return repaired_tree

        try:
            reduced = ddmin(test_lines, lines)
            reduced_source = '\n'.join(reduced)
            return ast.parse(reduced_source)
        except Exception:
            return repaired_tree
