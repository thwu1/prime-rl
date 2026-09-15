/* Extended Robertson Chemical Kinetics — complete C model with Jacobian
 *
 *
 * Four-species stiff reaction system with time-dependent forcing:
 *   dy1/dt = -k1*f(t)*y1 + k2*y2*y3
 *   dy2/dt =  k1*f(t)*y1 - k2*y2*y3 - k3*y2^2
 *   dy3/dt =  k3*y2^2 - k4*y3
 *   dy4/dt =  k4*y3
 */

#include <R.h>

static double parms[4];
static double forc[1];

#define k1 parms[0]
#define k2 parms[1]
#define k3 parms[2]
#define k4 parms[3]
#define fval forc[0]

void initmod(void (* odeparms)(int *, double *))
{
    int N = 4;
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

    ydot[0] = -k1 * fval * y[0] + k2 * y[1] * y[2];
    ydot[1] =  k1 * fval * y[0] - k2 * y[1] * y[2] - k3 * y[1] * y[1];
    ydot[2] =  k3 * y[1] * y[1] - k4 * y[2];
    ydot[3] =  k4 * y[2];

    yout[0] = y[0] + y[1] + y[2] + y[3];
}

/* Analytical Jacobian: pd[i + j*n] = d(ydot[i]) / d(y[j])
 * where n = *nrowpd (column-major, full Jacobian). */
void jac(int *neq, double *t, double *y, int *ml,
         int *mu, double *pd, int *nrowpd, double *yout, int *ip)
{
    int n = *nrowpd;

    /* Column 0: d(ydot_i)/d(y1) */
    pd[0 + 0 * n] = -k1 * fval;
    pd[1 + 0 * n] =  k1 * fval;
    pd[2 + 0 * n] =  0.0;
    pd[3 + 0 * n] =  0.0;

    /* Column 1: d(ydot_i)/d(y2) */
    pd[0 + 1 * n] =  k2 * y[2];
    pd[1 + 1 * n] = -k2 * y[2] - 2.0 * k3 * y[1];
    pd[2 + 1 * n] =  2.0 * k3 * y[1];
    pd[3 + 1 * n] =  0.0;

    /* Column 2: d(ydot_i)/d(y3) */
    pd[0 + 2 * n] =  k2 * y[1];
    pd[1 + 2 * n] = -k2 * y[1];
    pd[2 + 2 * n] = -k4;
    pd[3 + 2 * n] =  k4;

    /* Column 3: d(ydot_i)/d(y4) — y4 does not appear in any RHS */
    pd[0 + 3 * n] =  0.0;
    pd[1 + 3 * n] =  0.0;
    pd[2 + 3 * n] =  0.0;
    pd[3 + 3 * n] =  0.0;
}
