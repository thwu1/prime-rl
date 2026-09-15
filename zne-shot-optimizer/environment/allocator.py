"""
Shot allocation and variance estimation for Richardson extrapolation.

Provides optimal and uniform allocation strategies, along with
closed-form variance expressions for each.
"""


import math


def optimal_allocation(coefficients, total_budget):
    """
    Compute the variance-minimizing integer shot allocation for
    Richardson extrapolation under a fixed total shot budget.

    Uses the largest-remainder method for integer rounding.
    """
    weights = [c ** 2 for c in coefficients]
    total_weight = sum(weights)

    ideal = [total_budget * w / total_weight for w in weights]
    floors = [int(math.floor(x)) for x in ideal]

    remainders = [(ideal[i] - floors[i], i) for i in range(len(ideal))]
    remainders.sort(key=lambda x: -x[0])

    deficit = total_budget - sum(floors)
    for i in range(deficit):
        floors[remainders[i][1]] += 1

    return floors


def uniform_allocation(n, total_budget):
    """Uniform shot allocation across n scale factors."""
    base = total_budget // n
    remainder = total_budget - base * n
    alloc = [base] * n
    for i in range(remainder):
        alloc[i] += 1
    return alloc


def variance_uniform(coefficients, total_budget):
    """
    Variance with uniform allocation.
    Var = (n / M) * sum(gamma_j^2), assuming unit per-shot variance.
    """
    n = len(coefficients)
    return (n / total_budget) * sum(c ** 2 for c in coefficients)


def variance_optimal(coefficients, total_budget):
    """
    Variance with optimal allocation.
    Var = Gamma^2 / M, where Gamma = sum|gamma_j|.
    """
    gamma = sum(abs(c) for c in coefficients)
    return gamma ** 2 / total_budget
