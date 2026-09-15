#ifndef ELASTIC_CORE_H
#define ELASTIC_CORE_H

/*
 * 12x12 local elastic stiffness matrix for a 3D Euler-Bernoulli beam element.
 *
 * Parameters:
 *   E, nu, A, L, Iy, Iz, J  -- material and section properties
 *   k                        -- output buffer, 144 doubles (12x12, row-major)
 */
void local_elastic_stiffness_3D_c(
    double E, double nu, double A, double L,
    double Iy, double Iz, double J,
    double *k
);

/*
 * 12x12 coordinate transformation matrix for a 3D beam element.
 *
 * Parameters:
 *   x1,y1,z1  -- node i coordinates
 *   x2,y2,z2  -- node j coordinates
 *   ref_vec   -- 3-element reference direction vector (NULL for default)
 *   Gamma     -- output buffer, 144 doubles (12x12, row-major)
 */
void transformation_matrix_3D_c(
    double x1, double y1, double z1,
    double x2, double y2, double z2,
    const double *ref_vec,
    double *Gamma
);

#endif
