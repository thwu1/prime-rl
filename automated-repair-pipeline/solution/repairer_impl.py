"""Genetic programming search for automated program repair."""

import ast
import copy
import random
import signal
from typing import Any, Dict, List, Optional, Tuple

from .mutator import StatementMutator


class _EvalTimeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise _EvalTimeout()


def compute_fitness(tree: ast.AST, test_cases: List[Tuple[tuple, Any]],
                    func_name: str) -> float:
    """Evaluate fitness of a candidate AST. Returns fraction of tests passed.

    Uses SIGALRM to guard against infinite loops in mutated code.
    """
    try:
        code = compile(tree, '<repair>', 'exec')
    except (SyntaxError, ValueError, TypeError):
        return 0.0

    ns: Dict[str, Any] = {}
    try:
        exec(code, ns)
    except Exception:
        return 0.0

    fn = ns.get(func_name)
    if fn is None or not callable(fn):
        return 0.0

    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.setitimer(signal.ITIMER_REAL, 2.0)  # 2-second timeout for all tests

    passed = 0
    try:
        for args, expected in test_cases:
            try:
                result = fn(*args)
                if result == expected:
                    passed += 1
            except _EvalTimeout:
                raise
            except Exception:
                pass
    except _EvalTimeout:
        pass  # Timed out — return partial fitness
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)

    return passed / len(test_cases) if test_cases else 0.0


def crossover(tree1: ast.AST, tree2: ast.AST, func_name: str) -> Tuple[ast.AST, ast.AST]:
    """Crossover: swap body halves of two function defs."""
    t1 = copy.deepcopy(tree1)
    t2 = copy.deepcopy(tree2)

    fd1 = fd2 = None
    for n in ast.walk(t1):
        if isinstance(n, ast.FunctionDef) and n.name == func_name:
            fd1 = n
            break
    for n in ast.walk(t2):
        if isinstance(n, ast.FunctionDef) and n.name == func_name:
            fd2 = n
            break

    if fd1 is None or fd2 is None or not fd1.body or not fd2.body:
        return t1, t2

    b1 = fd1.body
    b2 = fd2.body
    cp1 = len(b1) // 2
    cp2 = len(b2) // 2

    new_b1 = b1[:cp1] + copy.deepcopy(b2[cp2:])
    new_b2 = b2[:cp2] + copy.deepcopy(b1[cp1:])

    fd1.body = new_b1 if new_b1 else [ast.Pass()]
    fd2.body = new_b2 if new_b2 else [ast.Pass()]

    ast.fix_missing_locations(t1)
    ast.fix_missing_locations(t2)
    return t1, t2


class GeneticRepairer:
    """Genetic programming search for program repair."""

    def __init__(self, population_size: int = 40, generations: int = 200,
                 func_name: str = ''):
        self.pop_size = population_size
        self.generations = generations
        self.func_name = func_name

    def repair(self, source_code: str,
               test_cases: List[Tuple[tuple, Any]],
               suspiciousness: Optional[Dict[Tuple[str, int], float]] = None) -> Tuple[ast.AST, float]:
        """Search for a repair. Returns (best_tree, best_fitness)."""
        tree = ast.parse(source_code)
        mutator = StatementMutator(suspiciousness=suspiciousness,
                                   func_name=self.func_name)

        # Initialize population: original + mutants
        population = [copy.deepcopy(tree)]
        for _ in range(self.pop_size - 1):
            population.append(mutator.mutate(tree))

        best_tree = tree
        best_fitness = compute_fitness(tree, test_cases, self.func_name)

        for gen in range(self.generations):
            # Evaluate all candidates
            scored = [(t, compute_fitness(t, test_cases, self.func_name))
                      for t in population]
            scored.sort(key=lambda x: x[1], reverse=True)

            if scored[0][1] > best_fitness:
                best_tree = scored[0][0]
                best_fitness = scored[0][1]

            if best_fitness >= 1.0:
                break

            # Selection: keep top half
            half = max(self.pop_size // 2, 2)
            survivors = [t for t, f in scored[:half]]

            # Generate offspring via mutation and crossover
            offspring: List[ast.AST] = []
            needed = self.pop_size - len(survivors)
            while len(offspring) < needed:
                if random.random() < 0.3 and len(survivors) >= 2:
                    p1, p2 = random.sample(survivors, 2)
                    c1, c2 = crossover(p1, p2, self.func_name)
                    offspring.append(c1)
                    if len(offspring) < needed:
                        offspring.append(c2)
                else:
                    parent = random.choice(survivors)
                    offspring.append(mutator.mutate(parent))

            population = survivors + offspring[:needed]

        return best_tree, best_fitness
