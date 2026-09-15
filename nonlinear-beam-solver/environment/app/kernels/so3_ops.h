/*
 * SO(3) rotation operations for geometrically exact beam elements.
 *
 * CONVENTION: All 3x3 rotation matrices are stored as flat arrays
 * of 9 doubles in COLUMN-MAJOR order (Fortran/LAPACK convention):
 *
 *   R[i + 3*j] = R_{ij}
 *
 * i.e. R[0..2] is column 0, R[3..5] is column 1, R[6..8] is column 2.
 *
 */

#ifndef SO3_OPS_H
#define SO3_OPS_H

/* Rotation vector to rotation matrix (Rodrigues formula).
 *   v : input rotation vector,  3 doubles
 *   R : output rotation matrix, 9 doubles (column-major)            */
void so3_rodrigues(const double *v, double *R);

/* Rotation matrix to rotation vector (matrix logarithm).
 *   R : input rotation matrix,  9 doubles (column-major)
 *   v : output rotation vector, 3 doubles                           */
void so3_log(const double *R, double *v);

#endif /* SO3_OPS_H */
