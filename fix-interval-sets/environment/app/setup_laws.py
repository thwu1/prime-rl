"""Ensure /app/laws.json exists during Docker build."""
import json
import os

LAWS = [
    {"name": "union_commutative", "description": "union(A, B) = union(B, A)", "num_sets": 2},
    {"name": "intersection_commutative", "description": "intersection(A, B) = intersection(B, A)", "num_sets": 2},
    {"name": "union_associative", "description": "union(union(A, B), C) = union(A, union(B, C))", "num_sets": 3},
    {"name": "intersection_associative", "description": "intersection(intersection(A, B), C) = intersection(A, intersection(B, C))", "num_sets": 3},
    {"name": "distributivity", "description": "union(A, intersection(B, C)) = intersection(union(A, B), union(A, C))", "num_sets": 3},
    {"name": "absorption_union", "description": "union(A, intersection(A, B)) = A", "num_sets": 2},
    {"name": "absorption_intersection", "description": "intersection(A, union(A, B)) = A", "num_sets": 2},
    {"name": "difference_decomposition", "description": "union(difference(A, B), difference(B, A)) = symmetric_difference(A, B)", "num_sets": 2},
    {"name": "demorgan_union", "description": "complement(union(A, B), 0, N) = intersection(complement(A, 0, N), complement(B, 0, N)) for A,B within [0, N)", "num_sets": 2},
    {"name": "demorgan_intersection", "description": "complement(intersection(A, B), 0, N) = union(complement(A, 0, N), complement(B, 0, N)) for A,B within [0, N)", "num_sets": 2},
    {"name": "complement_involution", "description": "complement(complement(A, 0, N), 0, N) = A for A within [0, N)", "num_sets": 1},
    {"name": "intersection_complement_empty", "description": "intersection(A, complement(A, 0, N)) = [] for A within [0, N)", "num_sets": 1},
]

os.makedirs('/app', exist_ok=True)
with open('/app/laws.json', 'w') as f:
    json.dump(LAWS, f, indent=2)
