#!/usr/bin/env python3
"""
Exact model counter for MC competition DIMACS format.
Supports mc (unweighted) and wmc (weighted) tracks.
Uses DPLL search with unit propagation, component decomposition, and memoization.

"""

import sys
import math
from fractions import Fraction
from decimal import Decimal
from collections import defaultdict


def parse_weight(s):
    """Parse a weight string (decimal, fraction, or scientific) into exact Fraction."""
    if '/' in s:
        num, den = s.split('/')
        return Fraction(int(num), int(den))
    return Fraction(Decimal(s))


def parse_dimacs(filename):
    """Parse DIMACS CNF with MC competition directives."""
    clauses = []
    num_vars = 0
    mode = 'mc'
    weights = {}

    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tokens = line.split()
            if tokens[0] == 'c':
                if len(tokens) >= 3 and tokens[1] == 't':
                    mode = tokens[2]
                elif (len(tokens) >= 6 and tokens[1] == 'p'
                      and tokens[2] == 'weight'):
                    lit = int(tokens[3])
                    weights[lit] = parse_weight(tokens[4])
            elif tokens[0] == 'p':
                num_vars = int(tokens[2])
            else:
                lits = [int(x) for x in tokens]
                if lits and lits[-1] == 0:
                    lits = lits[:-1]
                if lits:
                    clauses.append(tuple(lits))

    return num_vars, clauses, mode, weights


class ModelCounter:
    """DPLL-based exact model counter with component caching."""

    def __init__(self, num_vars, clauses, mode, weights):
        self.num_vars = num_vars
        self.clauses = clauses
        self.mode = mode
        self.weights = weights
        self.is_weighted = mode in ('wmc', 'pwmc', 'wpmc')
        self.cache = {}

    def lit_weight(self, lit):
        """Get weight of a literal."""
        if not self.is_weighted:
            return Fraction(1)
        return self.weights.get(lit, Fraction(1))

    def free_weight(self, var):
        """Get the combined weight of both polarities of a free variable."""
        return self.lit_weight(var) + self.lit_weight(-var)

    def simplify(self, clauses, var, val):
        """Simplify clause list after assigning var=val.
        Returns simplified clause list, or None on conflict (empty clause)."""
        result = []
        for clause in clauses:
            satisfied = False
            remaining = []
            for lit in clause:
                v = abs(lit)
                if v == var:
                    if (lit > 0) == val:
                        satisfied = True
                        break
                    # literal is false under this assignment, skip it
                else:
                    remaining.append(lit)
            if satisfied:
                continue
            if not remaining:
                return None  # empty clause = conflict
            result.append(tuple(remaining))
        return result

    def unit_propagate(self, clauses, unassigned):
        """Iteratively assign unit clauses.
        Returns (clauses, unassigned, accumulated_weight, conflict_flag)."""
        weight = Fraction(1)
        unass = set(unassigned)
        cls = list(clauses)

        changed = True
        while changed:
            changed = False
            for clause in cls:
                if len(clause) == 1:
                    lit = clause[0]
                    var = abs(lit)
                    val = lit > 0
                    weight *= self.lit_weight(lit)
                    unass.discard(var)
                    cls = self.simplify(cls, var, val)
                    if cls is None:
                        return None, None, None, True
                    changed = True
                    break  # restart scan after modification

        return cls, unass, weight, False

    def find_components(self, clauses, unassigned):
        """Group clauses into connected components by shared variables."""
        if not clauses:
            return []

        clause_vars = []
        for clause in clauses:
            cvars = frozenset(abs(lit) for lit in clause if abs(lit) in unassigned)
            clause_vars.append(cvars)

        var_to_cis = defaultdict(set)
        for i, cvs in enumerate(clause_vars):
            for v in cvs:
                var_to_cis[v].add(i)

        visited = set()
        components = []
        for start in range(len(clauses)):
            if start in visited:
                continue
            comp_cis = set()
            stack = [start]
            while stack:
                ci = stack.pop()
                if ci in visited:
                    continue
                visited.add(ci)
                comp_cis.add(ci)
                for v in clause_vars[ci]:
                    for adj_ci in var_to_cis[v]:
                        if adj_ci not in visited:
                            stack.append(adj_ci)

            comp_cls = [clauses[i] for i in comp_cis]
            comp_vs = set()
            for i in comp_cis:
                comp_vs |= clause_vars[i]
            components.append((comp_vs, comp_cls))

        return components

    def _free_count(self, free_vars):
        """Compute the count contribution of free (unconstrained) variables."""
        if not free_vars:
            return Fraction(1)
        if self.is_weighted:
            result = Fraction(1)
            for v in free_vars:
                result *= self.free_weight(v)
            return result
        return Fraction(2) ** len(free_vars)

    def count(self, clauses, unassigned):
        """Recursively count models with caching and component decomposition."""
        # Base: no clauses left
        if not clauses:
            return self._free_count(unassigned)

        # Unit propagation
        up_cls, up_unass, up_weight, conflict = self.unit_propagate(
            clauses, unassigned
        )
        if conflict:
            return Fraction(0)

        # All clauses satisfied after propagation
        if not up_cls:
            return up_weight * self._free_count(up_unass)

        # Separate free variables (not in any remaining clause) from active ones
        clause_vars = set()
        for clause in up_cls:
            for lit in clause:
                clause_vars.add(abs(lit))
        active = up_unass & clause_vars
        free = up_unass - clause_vars
        free_factor = self._free_count(free)

        # Cache lookup (key = normalized remaining clauses;
        # free vars are excluded so cache is independent of them)
        cache_key = tuple(sorted(up_cls))
        if cache_key in self.cache:
            return up_weight * free_factor * self.cache[cache_key]

        # Component decomposition
        components = self.find_components(up_cls, active)

        if len(components) > 1:
            result = Fraction(1)
            for comp_vars, comp_clauses in components:
                result *= self.count(comp_clauses, comp_vars)

            self.cache[cache_key] = result
            return up_weight * free_factor * result

        # Single component: branch on the most frequent variable
        var_freq = defaultdict(int)
        for clause in up_cls:
            for lit in clause:
                v = abs(lit)
                if v in active:
                    var_freq[v] += 1

        branch_var = max(var_freq, key=var_freq.get)

        result = Fraction(0)
        for val in [True, False]:
            lit = branch_var if val else -branch_var
            w = self.lit_weight(lit)
            new_cls = self.simplify(up_cls, branch_var, val)
            if new_cls is None:
                continue  # conflict on this branch
            new_unass = active - {branch_var}
            result += w * self.count(new_cls, new_unass)

        self.cache[cache_key] = result
        return up_weight * free_factor * result

    def solve(self):
        """Compute the exact model count."""
        all_vars = set(range(1, self.num_vars + 1))
        return self.count(list(self.clauses), all_vars)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <cnf_file>", file=sys.stderr)
        sys.exit(1)

    num_vars, clauses, mode, weights = parse_dimacs(sys.argv[1])
    counter = ModelCounter(num_vars, clauses, mode, weights)
    result = counter.solve()

    is_weighted = mode in ('wmc', 'pwmc', 'wpmc')

    if result == 0:
        print("s UNSATISFIABLE")
    else:
        print("s SATISFIABLE")

    if is_weighted:
        print("c s type wmc")
        print(f"c s exact arb float {float(result)}")
        frac = Fraction(result)
        print(f"c s exact rational {frac.numerator}/{frac.denominator}")
    else:
        count_int = int(result)
        print("c s type mc")
        if count_int > 0:
            print(f"c s log10-estimate {math.log10(count_int)}")
        print(f"c s exact arb int {count_int}")


if __name__ == '__main__':
    main()
