"""Automated program repair pipeline."""

import ast
import hashlib
import random
from typing import Any, Dict, List, Set, Tuple

from .coverage import CoverageCollector
from .fault_loc import ochiai
from .repairer import GeneticRepairer
from .minimizer import DeltaDebugMinimizer


def collect_test_coverage(source_code: str,
                          test_cases: List[Tuple[tuple, Any]],
                          func_name: str) -> Tuple[List[Set[Tuple[str, int]]],
                                                    List[Set[Tuple[str, int]]]]:
    """Run each test case, collect coverage, classify as pass/fail."""
    passed_cov: List[Set[Tuple[str, int]]] = []
    failed_cov: List[Set[Tuple[str, int]]] = []

    for args, expected in test_cases:
        ns: Dict[str, Any] = {}
        exec(compile(source_code, '<source>', 'exec'), ns)
        fn = ns[func_name]

        with CoverageCollector(func_name) as cc:
            try:
                result = fn(*args)
                is_pass = (result == expected)
            except Exception:
                is_pass = False

        cov = cc.coverage()
        if is_pass:
            passed_cov.append(cov)
        else:
            failed_cov.append(cov)

    return passed_cov, failed_cov


def repair_program(source_code: str,
                   test_cases: List[Tuple[tuple, Any]],
                   function_name: str) -> str:
    """Repair a buggy Python function using coverage-guided genetic programming.

    Args:
        source_code: Python source code containing the buggy function.
        test_cases: List of (args_tuple, expected_result) pairs.
        function_name: Name of the function to repair.

    Returns:
        Repaired Python source code as a string.

    Raises:
        RuntimeError: If no repair is found.
    """
    # Deterministic seed based on function name
    saved_state = random.getstate()
    seed = int(hashlib.md5(function_name.encode()).hexdigest(), 16) % (2**32)
    random.seed(seed)

    try:
        # Step 1: Collect coverage from test runs
        passed_cov, failed_cov = collect_test_coverage(
            source_code, test_cases, function_name
        )

        # Step 2: Compute Ochiai suspiciousness scores
        susp = ochiai(passed_cov, failed_cov)

        # Step 3: Genetic repair search
        repairer = GeneticRepairer(
            population_size=40, generations=200, func_name=function_name
        )
        best_tree, best_fitness = repairer.repair(
            source_code, test_cases, suspiciousness=susp
        )

        # Retry with different parameters if first attempt failed
        if best_fitness < 1.0:
            random.seed(seed + 1)
            repairer2 = GeneticRepairer(
                population_size=60, generations=300, func_name=function_name
            )
            tree2, fit2 = repairer2.repair(
                source_code, test_cases, suspiciousness=susp
            )
            if fit2 > best_fitness:
                best_tree = tree2
                best_fitness = fit2

        if best_fitness < 1.0:
            raise RuntimeError(
                f"Could not find repair for {function_name} "
                f"(best fitness: {best_fitness})"
            )

        # Step 4: Minimize the repair using delta debugging
        minimizer = DeltaDebugMinimizer(function_name)
        minimized = minimizer.minimize(best_tree, test_cases)

        return ast.unparse(minimized)

    finally:
        random.setstate(saved_state)
