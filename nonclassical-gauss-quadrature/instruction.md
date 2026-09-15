Compute N-point Gauss quadrature rules for three nonclassical weight functions defined in `/app/problem.json`, for N = 4, 8, 16, and 32. The weight functions are:

- **w1**: w(x) = -ln(x) on (0, 1), with known moments mu_k = 1/(k+1)^2
- **w2**: w(x) = x^(-1/4) (1-x)^(1/3) on (0, 1), with moments given by the Beta function
- **w3**: w(x) = exp(-x^4) on (0, infinity), with moments given by the Gamma function

For each weight function and order N, derive the three-term recurrence coefficients of the monic orthogonal polynomials from the moment sequence, then obtain the quadrature nodes and weights. Use the resulting rules to evaluate the integrals of specified smooth functions against each weight (detailed in `/app/problem.json`).

Write all results — quadrature nodes, weights, integral approximations, and moment-condition validation — to `/app/results.json` in the JSON format described in the specification file.