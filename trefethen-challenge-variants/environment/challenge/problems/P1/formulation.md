# Oscillatory Improper Integral

Compute the value of the following improper integral:

    I = lim_{eps -> 0+} integral from eps to 1 of x^{-1} * cos(alpha * x^{-1} * ln(x)) dx

The parameter `alpha` is defined in `params.json` in this directory.

The integrand oscillates with increasing frequency near x = 0, making this
a challenging numerical quadrature problem.
