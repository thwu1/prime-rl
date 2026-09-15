 */
#ifndef QUAD_WRAPPER_H
#define QUAD_WRAPPER_H

/* Function pointer type for integrands.
 * Accepts a double x and returns f(x). */
typedef double (*py_integrand)(double x);

/* Integrate f from a to b using the specified quadrature method.
 *
 * Methods:
 *   0 = QAG with Gauss-Kronrod 15-point rule
 *   1 = QAG with Gauss-Kronrod 21-point rule
 *   2 = QAG with Gauss-Kronrod 31-point rule
 *   3 = QAG with Gauss-Kronrod 41-point rule
 *   4 = QAG with Gauss-Kronrod 51-point rule
 *   5 = QAG with Gauss-Kronrod 61-point rule
 *   6 = QAGS (adaptive integration with endpoint singularity handling)
 *
 * Returns the estimated integral value.
 * Sets *abserr to the estimated absolute error.
 * Sets *neval to the number of subintervals used.
 * Sets *status to GSL status code (0 = success).
 */
double quad_integrate(py_integrand f, double a, double b,
                      double epsabs, double epsrel, int method,
                      double *abserr, int *neval, int *status);

#endif /* QUAD_WRAPPER_H */
