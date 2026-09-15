#!/usr/bin/env python3
"""Generate challenge polynomials for the root-finding and conditioning analysis task."""
import json

def poly_from_roots(roots):
    """Compute polynomial coefficients from roots, in descending order (highest degree first).
    Uses exact integer arithmetic when roots are integers."""
    coeffs = [1]
    for r in roots:
        new_coeffs = [0] * (len(coeffs) + 1)
        for i, c in enumerate(coeffs):
            new_coeffs[i] += c
            new_coeffs[i + 1] -= r * c
        coeffs = new_coeffs
    return coeffs

# P1: (x-1)(x-3)(x-5)(x-7)(x-9) -- well-separated real roots, degree 5
p1_coeffs = poly_from_roots([1, 3, 5, 7, 9])

# P2: x^6 + 1 -- all 6 roots are complex (6th roots of -1), degree 6
p2_coeffs = [1, 0, 0, 0, 0, 0, 1]

# P3: Wilkinson W_15 = (x-1)(x-2)...(x-15) -- moderately ill-conditioned, degree 15
p3_coeffs = poly_from_roots(list(range(1, 16)))

# P4: (x-1.0)(x-1.001)(x-1.002)(x-1.003)(x-5.0) -- clustered roots near x=1, degree 5
p4_coeffs = poly_from_roots([1.0, 1.001, 1.002, 1.003, 5.0])

# P5: Wilkinson W_20 = (x-1)(x-2)...(x-20) -- extremely ill-conditioned, degree 20
p5_coeffs = poly_from_roots(list(range(1, 21)))

data = {
    "polynomials": [
        {
            "id": 1,
            "name": "well_separated",
            "degree": 5,
            "coefficients_descending": [float(c) for c in p1_coeffs]
        },
        {
            "id": 2,
            "name": "all_complex",
            "degree": 6,
            "coefficients_descending": [float(c) for c in p2_coeffs]
        },
        {
            "id": 3,
            "name": "wilkinson_15",
            "degree": 15,
            "coefficients_descending": [float(c) for c in p3_coeffs]
        },
        {
            "id": 4,
            "name": "clustered",
            "degree": 5,
            "coefficients_descending": [float(c) for c in p4_coeffs]
        },
        {
            "id": 5,
            "name": "wilkinson_20",
            "degree": 20,
            "coefficients_descending": [float(c) for c in p5_coeffs]
        }
    ]
}

with open('/app/polynomials.json', 'w') as f:
    json.dump(data, f, indent=2)

print("Generated /app/polynomials.json with 5 challenge polynomials")
