"""RTL optimization pipeline — iterates passes to fixpoint."""

from rtl import deep_copy_function
from passes import constant_propagation, dead_code_elimination, branch_tunneling


def run_pipeline(func, max_rounds=20):
    current = deep_copy_function(func)
    for _ in range(max_rounds):
        prev = current.to_json()
        current = constant_propagation(current)
        current = dead_code_elimination(current)
        current = branch_tunneling(current)
        if current.to_json() == prev:
            break
    return current
