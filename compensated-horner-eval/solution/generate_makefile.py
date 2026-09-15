#!/usr/bin/env python3
"""Generate the Makefile for the polynomial evaluation pipeline."""

MAKEFILE = ".PHONY: all evaluate export\n\nall: evaluate export\n\nevaluate:\n\tpython3 /app/evaluator.py\n\nexport:\n\tsqlite3 -json /app/polyeval.db \"SELECT p.name, p.eval_point, r.compensated_value, r.error_bound, r.naive_value FROM results r JOIN polynomials p ON r.poly_id = p.id ORDER BY p.id;\" | jq '.' > /app/results.json\n"

with open('/app/Makefile', 'w') as f:
    f.write(MAKEFILE)
