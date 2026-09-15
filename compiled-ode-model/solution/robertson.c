/* Modified Robertson Chemical Kinetics - Compiled C model for deSolve
 *
 * System:
 *   dy1/dt = -k1*f(t)*y1 + k2*y2*y3
 *   dy2/dt =  k1*f(t)*y1 - k2*y2*y3 - k3*y2^2
 *   dy3/dt =  k3*y2^2
 *
 * where f(t) is a forcing function (temperature modulation).
 */


#include <R.h>

/* Static storage for parameters and forcing value */
static double parms[3];
static double forc[1];

/* Named access to parameters */
#define k1 parms[0]
#define k2 parms[1]
#define k3 parms[2]

/* Named access to forcing function value (auto-updated by solver) */
#define fval forc[0]

/* Parameter initialization: called once by deSolve to pass k1, k2, k3 */
void initmod(void (* odeparms)(int *, double *))
{
    int N = 3;
    odeparms(&N, parms);
}

/* Forcing function initialization: registers 1 forcing slot.
   The solver interpolates the forcing data and updates forc[0]
   at every integration step. */
void initforc(void (* odeforcs)(int *, double *))
{
    int N = 1;
    odeforcs(&N, forc);
}

/* Derivative function: computes dy/dt = f(t, y)
   Arguments follow the deSolve C interface convention. */
void derivs(int *neq, double *t, double *y, double *ydot,
            double *yout, int *ip)
{
    if (ip[0] < 1) error("nout should be at least 1");

    ydot[0] = -k1 * fval * y[0] + k2 * y[1] * y[2];
    ydot[1] =  k1 * fval * y[0] - k2 * y[1] * y[2] - k3 * y[1] * y[1];
    ydot[2] =  k3 * y[1] * y[1];

    /* Extra output: mass balance (should remain constant between events) */
    yout[0] = y[0] + y[1] + y[2];
}

/* Analytical Jacobian: full matrix, column-major storage.
   pd[i + j * nrowpd] = df_i / dy_j

   J = [ -k1*f     k2*y3          k2*y2       ]
       [  k1*f    -k2*y3-2*k3*y2  -k2*y2      ]
       [  0        2*k3*y2         0           ]
*/
void jac(int *neq, double *t, double *y, int *ml,
         int *mu, double *pd, int *nrowpd, double *yout, int *ip)
{
    int n = *nrowpd;

    /* Column 0: d(f_i)/d(y0) */
    pd[0 + 0 * n] = -k1 * fval;
    pd[1 + 0 * n] =  k1 * fval;
    pd[2 + 0 * n] =  0.0;

    /* Column 1: d(f_i)/d(y1) */
    pd[0 + 1 * n] =  k2 * y[2];
    pd[1 + 1 * n] = -k2 * y[2] - 2.0 * k3 * y[1];
    pd[2 + 1 * n] =  2.0 * k3 * y[1];

    /* Column 2: d(f_i)/d(y2) */
    pd[0 + 2 * n] =  k2 * y[1];
    pd[1 + 2 * n] = -k2 * y[1];
    pd[2 + 2 * n] =  0.0;
}
