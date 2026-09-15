
#ifndef LIBELLIPTIC_H
#define LIBELLIPTIC_H

#define MAX_LANDEN 30

typedef struct {
    double values[MAX_LANDEN];
    int length;
} LandenResult;

typedef struct {
    double real;
    double imag;
} CmplxResult;

LandenResult landen_sequence_c(double k, int n);
double complete_elliptic_K_c(double k);
CmplxResult elliptic_cd_c(double u_re, double u_im, double k);

#endif
