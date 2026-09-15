/*
 * 2D Poisson equation discretization utilities.
 *
 * Generates the sparse linear system for:
 *   -Laplacian(u) = f  on [0,1]^2
 *   u = 0              on boundary
 *
 * using the standard 5-point finite difference stencil
 * on n x n interior grid points (spacing h = 1/(n+1)).
 */

#ifndef STENCIL_H
#define STENCIL_H

/*
 * Generate and write the sparse system to Matrix Market files.
 *
 * Parameters:
 *   n           - number of interior grid points per direction
 *   matrix_file - output path for system matrix A (coordinate format)
 *   rhs_file    - output path for right-hand side b (array format)
 *
 * The forcing function is f(x,y) = 2*pi^2 * sin(pi*x) * sin(pi*y).
 * The RHS vector stores h^2 * f(x_j, y_i) in row-major grid order:
 *   index = i*n + j  corresponds to point (x_{j+1}, y_{i+1}).
 */
void generate_poisson_2d(int n, const char* matrix_file, const char* rhs_file);

#endif /* STENCIL_H */
