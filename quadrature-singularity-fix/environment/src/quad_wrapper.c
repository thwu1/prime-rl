 *
 * Wrapper around GSL numerical integration for Python ctypes consumption.
 *
 * Provides a simplified interface to GSL's adaptive quadrature routines,
 * accepting a C function pointer and dispatching to the appropriate
 * GSL integration method based on a method index parameter.
 *
 * Build: gcc -Wall -O2 -fPIC -shared -I./src -o libquad.so src/quad_wrapper.c -lgsl -lgslcblas -lm
 */

#include <stdlib.h>
#include <stdio.h>
#include <gsl_integration.h>
#include <gsl_errno.h>
#include "quad_wrapper.h"

/* Adapter: GSL expects gsl_function {double (*)(double, void*), void*}
 * but our py_integrand is just double (*)(double).
 * We pass the py_integrand as the void* params. */
static double gsl_adapter(double x, void *params) {
    py_integrand fn = (py_integrand)params;
    return fn(x);
}

double quad_integrate(py_integrand f, double a, double b,
                      double epsabs, double epsrel, int method,
                      double *abserr, int *neval, int *status) {
    gsl_function gsl_f;
    gsl_f.function = &gsl_adapter;
    gsl_f.params = (void *)f;

    double result = 0.0;
    *abserr = 0.0;
    *neval = 0;
    size_t limit = 2000;

    gsl_set_error_handler_off();

    gsl_integration_workspace *w = gsl_integration_workspace_alloc(limit);
    if (!w) {
        *status = -1;
        return 0.0;
    }

    int gsl_status = 0;

    if (method >= 0 && method <= 5) {
        /* Map method index to GSL Gauss-Kronrod key for qag */
        int key = method;
        gsl_status = gsl_integration_qag(&gsl_f, a, b, epsabs, epsrel,
                                          limit, key, w, &result, abserr);
    } else if (method == 6) {
        gsl_status = gsl_integration_qags(&gsl_f, a, b, epsabs, epsrel,
                                           limit, w, &result, abserr);
    } else {
        *status = -2;
        gsl_integration_workspace_free(w);
        return 0.0;
    }

    *neval = (int)w->size;
    *status = gsl_status;

    gsl_integration_workspace_free(w);

    return result;
}
