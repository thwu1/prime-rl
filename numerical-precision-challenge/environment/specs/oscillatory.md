# Parametric Oscillatory Integral

Compute the integral:

    I(a) = integral from 0 to infinity of cos(a * t * exp(t)) dt

for each parameter value `a` listed in the data file referenced by the challenge configuration.

This integral converges conditionally due to increasingly rapid oscillation of the integrand as t grows. The phase function a*t*exp(t) grows super-exponentially, making the integrand oscillate with unbounded frequency. Standard adaptive quadrature will fail; specialized techniques for oscillatory integrals are required.

## Output Format

Write one value per line to the output file specified in challenge.json, in the same order as the parameter values appear in the data file. Use plain decimal or scientific notation.
