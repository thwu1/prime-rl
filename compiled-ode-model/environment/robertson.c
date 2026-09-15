/* Robertson Chemical Kinetics - Compiled C model for deSolve
 *
 * Three-species stiff reaction system:
 *   A -> B    (rate k1, modulated by external forcing)
 *   B + C -> A + C  (rate k2)
 *   2B -> C   (rate k3)
 *
 * Rate constants: k1 = 0.04, k2 = 1e4, k3 = 3e7
 */

#include <R.h>

static double parms[3];
static double forc[1];

#define k1 parms[0]
#define k2 parms[1]
#define k3 parms[2]
#define fval forc[0]

void initmod(void (* odeparms)(int *, double *))
{
    int N = 3;
    odeparms(&N, parms);
}

void initforc(void (* odeforcs)(int *, double *))
{
    int N = 1;
    odeforcs(&N, forc);
}

void derivs(int *neq, double *t, double *y, double *ydot,
            double *yout, int *ip)
{
    if (ip[0] < 1) error("nout should be at least 1");

    ydot[0] = -k1 * y[0] + k2 * y[1] * y[2];
    ydot[1] =  k1 * y[0] - k2 * y[1] * y[2] - k3 * y[1] * y[1];
    ydot[2] =  k3 * y[1] * y[1];

    yout[0] = y[0] + y[1] + y[2];
}

void jac(int *neq, double *t, double *y, int *ml,
         int *mu, double *pd, int *nrowpd, double *yout, int *ip)
{
    int n = *nrowpd;

    pd[0 + 0 * n] = -k1;
    pd[1 + 0 * n] =  k1;
    pd[2 + 0 * n] =  0.0;

    pd[0 + 1 * n] =  k2 * y[2];
    pd[1 + 1 * n] = -k2 * y[2] - 2.0 * k3 * y[1];
    pd[2 + 1 * n] =  2.0 * k3 * y[1];

    pd[0 + 2 * n] =  k2 * y[1];
    pd[1 + 2 * n] =  k2 * y[1];
    pd[2 + 2 * n] =  0.0;
}
