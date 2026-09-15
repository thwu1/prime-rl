/*
 * cpamm.h — Constant-Product Automated Market Maker Pool Library
 *
 * Opaque-handle API for managing x·y=k liquidity pools.
 * All functions take a pool handle as the first argument.
 * Handles are heap-allocated; callers must free them with cpamm_free().
 *
 */

#ifndef CPAMM_H
#define CPAMM_H

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque pool handle — callers must not dereference */
typedef struct cpamm_pool cpamm_pool_t;

/*
 * Allocate and initialise a new pool with the given reserves.
 * Both reserves must be strictly positive.
 * Returns NULL on invalid input or allocation failure.
 */
cpamm_pool_t *cpamm_create(double reserve_x, double reserve_y);

/* Release all memory associated with pool. Safe to call on NULL. */
void cpamm_free(cpamm_pool_t *pool);

/* Query the current X reserve. Returns -1.0 if pool is NULL. */
double cpamm_get_x(const cpamm_pool_t *pool);

/* Query the current Y reserve. Returns -1.0 if pool is NULL. */
double cpamm_get_y(const cpamm_pool_t *pool);

/* Query the pool invariant k = x * y. Returns -1.0 if pool is NULL. */
double cpamm_get_k(const cpamm_pool_t *pool);

/*
 * Update both reserves atomically.
 * Validates that new_x * new_y == k within a relative tolerance of 1e-9.
 *
 * Return codes:
 *   0  — success
 *  -1  — pool is NULL
 *  -2  — one or both reserves are non-positive
 *  -3  — invariant violation (new_x * new_y deviates from k)
 */
int cpamm_set_reserves(cpamm_pool_t *pool, double new_x, double new_y);

/* Marginal price: reserve_y / reserve_x. Returns -1.0 on error. */
double cpamm_spot_price(const cpamm_pool_t *pool);

#ifdef __cplusplus
}
#endif

#endif /* CPAMM_H */
