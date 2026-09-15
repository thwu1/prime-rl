/*
 * coeffgen.c — Polynomial coefficient computation for depth-corrected
 *              relative pose estimation.
 *
 *
 * Build:
 *   gcc -shared -fPIC -O2 -o libcoeffgen.so coeffgen.c
 *
 * API:
 *   void compute_coefficients(
 *       const double *x1,     // 3x3 row-major: three homogeneous 2D points, cam 1
 *       const double *x2,     // 3x3 row-major: three homogeneous 2D points, cam 2
 *       const double *d1,     // 3 observed depths, cam 1
 *       const double *d2,     // 3 observed depths, cam 2
 *       double *coeffs        // output: 18 doubles (6 per point pair)
 *   );
 *
 * The three pairwise distance consistency constraints (pairs (0,1), (0,2),
 * (1,2)) each yield a degree-2 polynomial in the unknown affine parameters
 * (b1, a2, b2)  [with a1 fixed to 1].
 *
 * For pair k (k = 0, 1, 2), the constraint equation is:
 *
 *   c[6k+0]*b2^2  +  c[6k+1]*b1^2  +  c[6k+2]*a2*b2  +  c[6k+3]*a2^2
 *   + c[6k+4]*b1  +  c[6k+5]  =  0
 *
 * where the 6 coefficients per pair are derived from dot products of the
 * homogeneous point coordinates and the observed depth values.
 */

static double dot3(const double *a, const double *b) {
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
}

void compute_coefficients(
    const double *x1,
    const double *x2,
    const double *d1,
    const double *d2,
    double *coeffs
) {
    int pairs[3][2] = {{0, 1}, {0, 2}, {1, 2}};
    int k, i, j, base;

    for (k = 0; k < 3; k++) {
        i = pairs[k][0];
        j = pairs[k][1];

        const double *x1i = x1 + i * 3;
        const double *x1j = x1 + j * 3;
        const double *x2i = x2 + i * 3;
        const double *x2j = x2 + j * 3;

        double P1_ii = dot3(x1i, x1i);
        double P1_jj = dot3(x1j, x1j);
        double P1_ij = dot3(x1i, x1j);
        double P2_ii = dot3(x2i, x2i);
        double P2_jj = dot3(x2j, x2j);
        double P2_ij = dot3(x2i, x2j);

        base = 6 * k;

        /* coeff of b2^2 */
        coeffs[base + 0] = 2.0*P2_ij - P2_ii - P2_jj;

        /* coeff of b1^2 */
        coeffs[base + 1] = P1_ii + P1_jj - 2.0*P1_ij;

        /* coeff of a2*b2 */
        coeffs[base + 2] = 2.0*(d2[i] + d2[j])*P2_ij
                         - 2.0*d2[i]*P2_ii
                         - 2.0*d2[j]*P2_jj;

        /* coeff of a2^2 */
        coeffs[base + 3] = 2.0*d2[i]*d2[j]*P2_ij
                         - d2[i]*d2[i]*P2_ii
                         - d2[j]*d2[j]*P2_jj;

        /* coeff of b1 (linear) */
        coeffs[base + 4] = 2.0*d1[i]*P1_ii
                         + 2.0*d1[j]*P1_jj
                         - 2.0*(d1[i] + d1[j])*P1_ij;

        /* constant term */
        coeffs[base + 5] = d1[i]*d1[i]*P1_ii
                         + d1[j]*d1[j]*P1_jj
                         - 2.0*d1[i]*d1[j]*P1_ij;
    }
}
