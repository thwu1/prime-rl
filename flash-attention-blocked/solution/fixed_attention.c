#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "blocked_attention.h"

/* Non-causal forward pass */
void blocked_forward(
    const double *Q, const double *K, const double *V,
    double *O, double *L,
    int N, int d, int block_size)
{
    double scale = 1.0 / sqrt((double)d);
    int num_blocks = (N + block_size - 1) / block_size;

    double *mi      = (double *)malloc(block_size * sizeof(double));
    double *li      = (double *)malloc(block_size * sizeof(double));
    double *acc     = (double *)malloc(block_size * d * sizeof(double));
    double *sij     = (double *)malloc(block_size * block_size * sizeof(double));
    double *pij     = (double *)malloc(block_size * block_size * sizeof(double));
    double *mij_buf = (double *)malloc(block_size * sizeof(double));
    double *lij     = (double *)malloc(block_size * sizeof(double));

    for (int bi = 0; bi < num_blocks; bi++) {
        int i_s = bi * block_size;
        int i_e = i_s + block_size;
        if (i_e > N) i_e = N;
        int br = i_e - i_s;

        for (int r = 0; r < br; r++) {
            mi[r] = -INFINITY;
            li[r] = 0.0;
        }
        memset(acc, 0, br * d * sizeof(double));

        for (int bj = 0; bj < num_blocks; bj++) {
            int j_s = bj * block_size;
            int j_e = j_s + block_size;
            if (j_e > N) j_e = N;
            int bc = j_e - j_s;

            for (int r = 0; r < br; r++) {
                for (int c = 0; c < bc; c++) {
                    double dot = 0.0;
                    for (int k = 0; k < d; k++)
                        dot += Q[(i_s + r) * d + k] * K[(j_s + c) * d + k];
                    sij[r * block_size + c] = dot * scale;
                }
            }

            for (int r = 0; r < br; r++) {
                double mx = sij[r * block_size];
                for (int c = 1; c < bc; c++) {
                    double v = sij[r * block_size + c];
                    if (v > mx) mx = v;
                }
                mij_buf[r] = mx;
            }

            for (int r = 0; r < br; r++) {
                lij[r] = 0.0;
                for (int c = 0; c < bc; c++) {
                    pij[r * block_size + c] =
                        exp(sij[r * block_size + c] - mij_buf[r]);
                    lij[r] += pij[r * block_size + c];
                }
            }

            for (int r = 0; r < br; r++) {
                double mi_new = (mi[r] > mij_buf[r]) ? mi[r] : mij_buf[r];
                double alpha  = exp(mi[r]      - mi_new);
                double beta   = exp(mij_buf[r] - mi_new);
                double li_new = li[r] * alpha + lij[r] * beta;

                for (int k = 0; k < d; k++) {
                    double pv = 0.0;
                    for (int c = 0; c < bc; c++)
                        pv += pij[r * block_size + c] *
                              V[(j_s + c) * d + k];
                    acc[r * d + k] = alpha * acc[r * d + k] + beta * pv;
                }
                mi[r] = mi_new;
                li[r] = li_new;
            }
        }

        for (int r = 0; r < br; r++) {
            for (int k = 0; k < d; k++)
                O[(i_s + r) * d + k] = acc[r * d + k] / li[r];
            L[i_s + r] = mi[r] + log(li[r]);
        }
    }

    free(mi); free(li); free(acc);
    free(sij); free(pij); free(mij_buf); free(lij);
}


/* Causal forward pass */
void blocked_causal_forward(
    const double *Q, const double *K, const double *V,
    double *O, double *L,
    int N, int d, int block_size)
{
    double scale = 1.0 / sqrt((double)d);
    int num_blocks = (N + block_size - 1) / block_size;

    double *mi      = (double *)malloc(block_size * sizeof(double));
    double *li      = (double *)malloc(block_size * sizeof(double));
    double *acc     = (double *)malloc(block_size * d * sizeof(double));
    double *sij     = (double *)malloc(block_size * block_size * sizeof(double));
    double *pij     = (double *)malloc(block_size * block_size * sizeof(double));
    double *mij_buf = (double *)malloc(block_size * sizeof(double));
    double *lij     = (double *)malloc(block_size * sizeof(double));

    for (int bi = 0; bi < num_blocks; bi++) {
        int i_s = bi * block_size;
        int i_e = i_s + block_size;
        if (i_e > N) i_e = N;
        int br = i_e - i_s;

        for (int r = 0; r < br; r++) {
            mi[r] = -INFINITY;
            li[r] = 0.0;
        }
        memset(acc, 0, br * d * sizeof(double));

        for (int bj = 0; bj <= bi; bj++) {
            int j_s = bj * block_size;
            int j_e = j_s + block_size;
            if (j_e > N) j_e = N;
            int bc = j_e - j_s;

            for (int r = 0; r < br; r++) {
                for (int c = 0; c < bc; c++) {
                    double dot = 0.0;
                    for (int k = 0; k < d; k++)
                        dot += Q[(i_s + r) * d + k] * K[(j_s + c) * d + k];
                    sij[r * block_size + c] = dot * scale;
                }
            }

            /* Causal mask on diagonal block */
            if (bi == bj) {
                for (int r = 0; r < br; r++)
                    for (int c = 0; c < bc; c++)
                        if (i_s + r < j_s + c)
                            sij[r * block_size + c] = -INFINITY;
            }

            for (int r = 0; r < br; r++) {
                double mx = sij[r * block_size];
                for (int c = 1; c < bc; c++) {
                    double v = sij[r * block_size + c];
                    if (v > mx) mx = v;
                }
                mij_buf[r] = mx;
            }

            for (int r = 0; r < br; r++) {
                lij[r] = 0.0;
                for (int c = 0; c < bc; c++) {
                    pij[r * block_size + c] =
                        exp(sij[r * block_size + c] - mij_buf[r]);
                    lij[r] += pij[r * block_size + c];
                }
            }

            for (int r = 0; r < br; r++) {
                double mi_new = (mi[r] > mij_buf[r]) ? mi[r] : mij_buf[r];
                double alpha  = exp(mi[r]      - mi_new);
                double beta   = exp(mij_buf[r] - mi_new);
                double li_new = li[r] * alpha + lij[r] * beta;

                for (int k = 0; k < d; k++) {
                    double pv = 0.0;
                    for (int c = 0; c < bc; c++)
                        pv += pij[r * block_size + c] *
                              V[(j_s + c) * d + k];
                    acc[r * d + k] = alpha * acc[r * d + k] + beta * pv;
                }
                mi[r] = mi_new;
                li[r] = li_new;
            }
        }

        for (int r = 0; r < br; r++) {
            for (int k = 0; k < d; k++)
                O[(i_s + r) * d + k] = acc[r * d + k] / li[r];
            L[i_s + r] = mi[r] + log(li[r]);
        }
    }

    free(mi); free(li); free(acc);
    free(sij); free(pij); free(mij_buf); free(lij);
}


/* Non-causal backward pass */
void blocked_backward(
    const double *Q, const double *K, const double *V,
    const double *O, const double *dO, const double *L,
    double *dQ, double *dK, double *dV,
    int N, int d, int block_size)
{
    double scale = 1.0 / sqrt((double)d);
    int num_blocks = (N + block_size - 1) / block_size;

    double *D = (double *)malloc(N * sizeof(double));
    for (int r = 0; r < N; r++) {
        D[r] = 0.0;
        for (int k = 0; k < d; k++)
            D[r] += dO[r * d + k] * O[r * d + k];
    }

    memset(dQ, 0, N * d * sizeof(double));
    memset(dK, 0, N * d * sizeof(double));
    memset(dV, 0, N * d * sizeof(double));

    double *sij      = (double *)malloc(block_size * block_size * sizeof(double));
    double *p_ij     = (double *)malloc(block_size * block_size * sizeof(double));
    double *dS_block = (double *)malloc(block_size * block_size * sizeof(double));

    for (int bi = 0; bi < num_blocks; bi++) {
        int i_s = bi * block_size;
        int i_e = i_s + block_size;
        if (i_e > N) i_e = N;
        int br = i_e - i_s;

        for (int bj = 0; bj < num_blocks; bj++) {
            int j_s = bj * block_size;
            int j_e = j_s + block_size;
            if (j_e > N) j_e = N;
            int bc = j_e - j_s;

            for (int r = 0; r < br; r++) {
                for (int c = 0; c < bc; c++) {
                    double dot = 0.0;
                    for (int k = 0; k < d; k++)
                        dot += Q[(i_s + r) * d + k] * K[(j_s + c) * d + k];
                    sij[r * block_size + c] = dot * scale;
                }
            }

            for (int r = 0; r < br; r++)
                for (int c = 0; c < bc; c++)
                    p_ij[r * block_size + c] =
                        exp(sij[r * block_size + c] - L[i_s + r]);

            for (int c = 0; c < bc; c++) {
                for (int k = 0; k < d; k++) {
                    double val = 0.0;
                    for (int r = 0; r < br; r++)
                        val += p_ij[r * block_size + c] *
                               dO[(i_s + r) * d + k];
                    dV[(j_s + c) * d + k] += val;
                }
            }

            for (int r = 0; r < br; r++) {
                for (int c = 0; c < bc; c++) {
                    double dp = 0.0;
                    for (int k = 0; k < d; k++)
                        dp += dO[(i_s + r) * d + k] *
                              V[(j_s + c) * d + k];
                    dS_block[r * block_size + c] =
                        p_ij[r * block_size + c] * (dp - D[i_s + r]);
                }
            }

            for (int r = 0; r < br; r++) {
                for (int k = 0; k < d; k++) {
                    double val = 0.0;
                    for (int c = 0; c < bc; c++)
                        val += dS_block[r * block_size + c] *
                               K[(j_s + c) * d + k];
                    dQ[(i_s + r) * d + k] += val * scale;
                }
            }

            for (int c = 0; c < bc; c++) {
                for (int k = 0; k < d; k++) {
                    double val = 0.0;
                    for (int r = 0; r < br; r++)
                        val += dS_block[r * block_size + c] *
                               Q[(i_s + r) * d + k];
                    dK[(j_s + c) * d + k] += val * scale;
                }
            }
        }
    }

    free(D);
    free(sij);
    free(p_ij);
    free(dS_block);
}


/* Causal backward pass */
void blocked_causal_backward(
    const double *Q, const double *K, const double *V,
    const double *O, const double *dO, const double *L,
    double *dQ, double *dK, double *dV,
    int N, int d, int block_size)
{
    double scale = 1.0 / sqrt((double)d);
    int num_blocks = (N + block_size - 1) / block_size;

    double *D = (double *)malloc(N * sizeof(double));
    for (int r = 0; r < N; r++) {
        D[r] = 0.0;
        for (int k = 0; k < d; k++)
            D[r] += dO[r * d + k] * O[r * d + k];
    }

    memset(dQ, 0, N * d * sizeof(double));
    memset(dK, 0, N * d * sizeof(double));
    memset(dV, 0, N * d * sizeof(double));

    double *sij      = (double *)malloc(block_size * block_size * sizeof(double));
    double *p_ij     = (double *)malloc(block_size * block_size * sizeof(double));
    double *dS_block = (double *)malloc(block_size * block_size * sizeof(double));

    for (int bi = 0; bi < num_blocks; bi++) {
        int i_s = bi * block_size;
        int i_e = i_s + block_size;
        if (i_e > N) i_e = N;
        int br = i_e - i_s;

        for (int bj = 0; bj <= bi; bj++) {
            int j_s = bj * block_size;
            int j_e = j_s + block_size;
            if (j_e > N) j_e = N;
            int bc = j_e - j_s;

            for (int r = 0; r < br; r++) {
                for (int c = 0; c < bc; c++) {
                    double dot = 0.0;
                    for (int k = 0; k < d; k++)
                        dot += Q[(i_s + r) * d + k] * K[(j_s + c) * d + k];
                    sij[r * block_size + c] = dot * scale;
                }
            }

            /* Causal mask on diagonal block */
            if (bi == bj) {
                for (int r = 0; r < br; r++)
                    for (int c = 0; c < bc; c++)
                        if (i_s + r < j_s + c)
                            sij[r * block_size + c] = -INFINITY;
            }

            for (int r = 0; r < br; r++)
                for (int c = 0; c < bc; c++)
                    p_ij[r * block_size + c] =
                        exp(sij[r * block_size + c] - L[i_s + r]);

            for (int c = 0; c < bc; c++) {
                for (int k = 0; k < d; k++) {
                    double val = 0.0;
                    for (int r = 0; r < br; r++)
                        val += p_ij[r * block_size + c] *
                               dO[(i_s + r) * d + k];
                    dV[(j_s + c) * d + k] += val;
                }
            }

            for (int r = 0; r < br; r++) {
                for (int c = 0; c < bc; c++) {
                    double dp = 0.0;
                    for (int k = 0; k < d; k++)
                        dp += dO[(i_s + r) * d + k] *
                              V[(j_s + c) * d + k];
                    dS_block[r * block_size + c] =
                        p_ij[r * block_size + c] * (dp - D[i_s + r]);
                }
            }

            for (int r = 0; r < br; r++) {
                for (int k = 0; k < d; k++) {
                    double val = 0.0;
                    for (int c = 0; c < bc; c++)
                        val += dS_block[r * block_size + c] *
                               K[(j_s + c) * d + k];
                    dQ[(i_s + r) * d + k] += val * scale;
                }
            }

            for (int c = 0; c < bc; c++) {
                for (int k = 0; k < d; k++) {
                    double val = 0.0;
                    for (int r = 0; r < br; r++)
                        val += dS_block[r * block_size + c] *
                               Q[(i_s + r) * d + k];
                    dK[(j_s + c) * d + k] += val * scale;
                }
            }
        }
    }

    free(D);
    free(sij);
    free(p_ij);
    free(dS_block);
}
