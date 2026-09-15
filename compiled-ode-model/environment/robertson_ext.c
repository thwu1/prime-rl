/* Extended Robertson Chemical Kinetics — compiled C model for deSolve
 *
 * Four-species stiff reaction system with time-dependent forcing:
 *   dy1/dt = -k1*f(t)*y1 + k2*y2*y3
 *   dy2/dt =  k1*f(t)*y1 - k2*y2*y3 - k3*y2^2
 *   dy3/dt =  k3*y2^2 - k4*y3
 *   dy4/dt =  k4*y3
 *
 * Rate constants: k1=0.04, k2=1e4, k3=3e7, k4=1e-3
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

/* TODO: Implement the analytical Jacobian function for use with stiff
 * solvers. The function must follow deSolve's compiled-code Jacobian
 * interface for full user-supplied Jacobians (jactype = "fullusr").
 * Consult the deSolve "compiledCode" vignette for the required
 * function signature and the column-major storage convention. */
