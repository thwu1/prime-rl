/*
 * Batch Gaussian Mixture log-PDF computation with numerical stability.
 *
 * Compile:  gcc -shared -fPIC -O2 -o libgm_logpdf.so gm_logpdf.c -lm
 *
 */

#include <math.h>
#include <stdlib.h>
#include <float.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/*
 * Compute log-probabilities of N samples under a K-component
 * isotropic Gaussian mixture in D dimensions.
 *
 * Parameters:
 *   N            - number of evaluation points
 *   K            - number of mixture components
 *   D            - data dimensionality
 *   samples      - row-major array of shape (N, D)
 *   means        - row-major array of shape (K, D)
 *   logstd       - shared log standard deviation (scalar)
 *   logweights   - array of length K (unnormalized log mixing weights)
 *   output       - array of length N (computed log-probabilities)
 *
 * For each sample n, computes:
 *
 *     output[n] = logsumexp_k [ logweight_k + log N(sample_n ; mean_k, sigma^2 I) ]
 *
 * where sigma = exp(logstd) and logweight_k is used directly (unnormalized).
 *
 * The full Gaussian normalisation constant (-D/2 * log(2*pi)) is
 * included.  Use the log-sum-exp trick for numerical stability.
 */
void gm_logpdf_batch(
    int N, int K, int D,
    const double *samples,
    const double *means,
    double logstd,
    const double *logweights,
    double *output
) {
    /* TODO: implement gm_logpdf_batch */
}
