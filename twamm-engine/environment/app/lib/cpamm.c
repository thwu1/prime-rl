/*
 * cpamm.c — Constant-Product AMM pool implementation
 *
 */

#include "cpamm.h"
#include <stdlib.h>
#include <math.h>

#define K_REL_TOL 1e-9

struct cpamm_pool {
    double x;
    double y;
    double k;
};

cpamm_pool_t *cpamm_create(double reserve_x, double reserve_y) {
    if (reserve_x <= 0.0 || reserve_y <= 0.0)
        return NULL;
    cpamm_pool_t *pool = (cpamm_pool_t *)malloc(sizeof(cpamm_pool_t));
    if (!pool)
        return NULL;
    pool->x = reserve_x;
    pool->y = reserve_y;
    pool->k = reserve_x * reserve_y;
    return pool;
}

void cpamm_free(cpamm_pool_t *pool) {
    free(pool);  /* free(NULL) is safe per C standard */
}

double cpamm_get_x(const cpamm_pool_t *pool) {
    if (!pool) return -1.0;
    return pool->x;
}

double cpamm_get_y(const cpamm_pool_t *pool) {
    if (!pool) return -1.0;
    return pool->y;
}

double cpamm_get_k(const cpamm_pool_t *pool) {
    if (!pool) return -1.0;
    return pool->k;
}

int cpamm_set_reserves(cpamm_pool_t *pool, double new_x, double new_y) {
    if (!pool)
        return -1;
    if (new_x <= 0.0 || new_y <= 0.0)
        return -2;
    double new_k = new_x * new_y;
    double rel_err = fabs(new_k - pool->k) / pool->k;
    if (rel_err > K_REL_TOL)
        return -3;
    pool->x = new_x;
    pool->y = new_y;
    /* k stays at original value — rounding drift is intentional */
    return 0;
}

double cpamm_spot_price(const cpamm_pool_t *pool) {
    if (!pool || pool->x <= 0.0)
        return -1.0;
    return pool->y / pool->x;
}
