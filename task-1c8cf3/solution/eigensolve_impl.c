 */

#include "eigensolve.h"
#include <string.h>

/* LAPACK Fortran interface for general eigenvalue problem */
extern void dgeev_(char *jobvl, char *jobvr, int *n, double *a, int *lda,
                   double *wr, double *wi, double *vl, int *ldvl,
                   double *vr, int *ldvr, double *work, int *lwork, int *info);

int eig4x4(const double *A, double *wr, double *wi, double *vr) {
    int n = 4;
    double a_col[16];   /* column-major copy for LAPACK */
    double vr_col[16];  /* eigenvectors in column-major */
    double vl_dummy[16];
    double work[256];
    int lwork = 256;
    int info;
    char jobvl = 'N';
    char jobvr = 'V';
    int i, j;

    /* Convert A from row-major (C) to column-major (Fortran) storage */
    for (i = 0; i < 4; i++)
        for (j = 0; j < 4; j++)
            a_col[i + j * 4] = A[i * 4 + j];

    dgeev_(&jobvl, &jobvr, &n, a_col, &n, wr, wi,
           vl_dummy, &n, vr_col, &n, work, &lwork, &info);

    if (info != 0)
        return info;

    /* Convert eigenvectors from column-major to row-major:
     * vr[i*4+j] = component i of eigenvector j */
    for (i = 0; i < 4; i++)
        for (j = 0; j < 4; j++)
            vr[i * 4 + j] = vr_col[i + j * 4];

    return 0;
}
