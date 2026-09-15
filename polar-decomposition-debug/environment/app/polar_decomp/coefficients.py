# Classical 5th-order Newton-Schulz coefficients (a, b, c) for the polynomial
# p(r) = a + b*r + c*r^2 applied as X <- p(XX^T) X.
# Fixed point at sigma=1: p(1) = a + b + c = 1.
# Superlinear convergence: p'(1)*1 + p(1) = a + 3b + 5c + 1 = 0 => a + 3b + 5c = 0.
# Solving: a = 15/8, b = -5/4, c = 3/8.
CLASSICAL_COEFFICIENTS = [(1.875, -1.25, 0.375)] * 7

# Optimized per-iteration coefficients from You et al., tuned for fast convergence
# across the practical singular-value range after Frobenius normalization.
# These do NOT individually satisfy p(1)=1; their composition does approximately.
YOU_COEFFICIENTS = [
    (4.0848, -6.8946, 2.9270),
    (3.9505, -6.3029, 2.6377),
    (3.7418, -5.5913, 2.3037),
    (2.8769, -3.1427, 1.2046),
    (2.8366, -3.0525, 1.2012),
]
