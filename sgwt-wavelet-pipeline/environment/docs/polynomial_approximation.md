# Polynomial Approximation Methods

## Chebyshev Polynomial Approximation

Instead of computing the full eigendecomposition, the graph filter
g(L) can be approximated using Chebyshev polynomials of the first
kind, evaluated via a matrix three-term recurrence.

### Domain mapping

The eigenvalue interval [0, lambda_max] is mapped to the Chebyshev
domain [-1, 1]:

    a1 = lambda_max / 2
    a2 = lambda_max / 2
    L' = (L - a2 I) / a1

### Three-term recurrence

The Chebyshev polynomials satisfy:

    T_0(x) = 1
    T_1(x) = x
    T_{k+1}(x) = 2 x T_k(x) - T_{k-1}(x)

In matrix form on the rescaled Laplacian this becomes:

    T_{k+1}(L') s = (2/a1)(L - a2 I) T_k(L') s  -  T_{k-1}(L') s

The filtered signal is then:

    g(L) s  ~  (c_0 / 2) T_0(L') s  +  sum_{k=1}^{m} c_k T_k(L') s

### Coefficient computation

Chebyshev coefficients are computed by DCT-like quadrature on m+1
Chebyshev nodes distributed over [-1, 1]:

    x_j = cos( pi (j + 0.5) / (m+1) )    for j = 0, ..., m

    c_k = (2 / (m+1)) sum_{j=0}^{m} f(a1 x_j + a2) cos( pi k (j+0.5) / (m+1) )

---

## Frame Bounds

Given a filterbank {g_0, g_1, ..., g_{Nf-1}} evaluated at eigenvalues
{lambda_1, ..., lambda_N}, the frame bounds are:

    A = min_j  sum_i  g_i(lambda_j)^2
    B = max_j  sum_i  g_i(lambda_j)^2

A tight frame has A = B.  For perfect reconstruction the filterbank
should be designed so that A = B = 1.

---

## Jackson-Chebyshev Damping

To reduce Gibbs oscillations when approximating a discontinuous
function (such as an ideal band-pass indicator) by a truncated
Chebyshev series, the raw coefficients can be multiplied by Jackson
damping weights.

### Ideal band-pass Chebyshev expansion

The Chebyshev expansion of the indicator function for the interval
[a, b] mapped to the standard Chebyshev domain [-1, 1] via:

    a1 = (lambda_max - lambda_min) / 2
    a2 = (lambda_max + lambda_min) / 2
    a' = (a - a2) / a1
    b' = (b - a2) / a1

gives the coefficients:

    ch_0 = (2 / pi) ( arccos(a') - arccos(b') )
    ch_k = (2 / (pi k)) ( sin(k arccos(a')) - sin(k arccos(b')) )

### Jackson damping factors

Given polynomial order m, define:

    alpha = pi / (m + 2)

The Jackson damping factor for the k-th coefficient is:

    gamma_k = (1 / sin(alpha)) *
              [ (1 - k/(m+2)) sin(alpha) cos(k alpha)
              + (1/(m+2))     cos(alpha) sin(k alpha) ]

The final damped coefficients are then  ch_k * gamma_k.  The function
should return these combined (element-wise product) coefficients.
