#ifndef MANIPULATOR_H
#define MANIPULATOR_H


// 6-DOF serial manipulator with spherical wrist
//
// DH Parameters (standard convention):
//   Joint  alpha       a          d
//   1      PI/2        0          0.15185
//   2      0          -0.37082    0
//   3      0          -0.28956    0
//   4      PI/2        0          0.10483
//   5     -PI/2        0          0.08793
//   6      0           0          0.07506
//
// The forward() function computes T_base_ee = T_base_0 * T_0_6(q) * T_6_ee
// where T_0_6(q) is the standard DH forward kinematics chain, and
// T_base_0, T_6_ee are fixed offset transforms applied internally.

namespace manipulator {
    // Forward kinematics
    // @param q    6 joint angles in radians
    // @param T    Output 4x4 homogeneous transform matrix, row-major (16 doubles)
    void forward(const double* q, double* T);

    // Inverse kinematics
    // @param T       4x4 end-effector pose, row-major (16 doubles)
    // @param q_sols  Output: up to 8 solutions, each 6 joint angles (8x6 = 48 doubles)
    // @param q6_des  Desired q6 when wrist singularity makes q6 arbitrary (default 0.0)
    // @return        Number of valid solutions found (0 to 8)
    //
    // All returned joint angles must be in [0, 2*PI).
    // For each solution, forward(solution) must match the input T within
    // 1e-6 Frobenius norm.
    int inverse(const double* T, double* q_sols, double q6_des = 0.0);
}

#endif // MANIPULATOR_H
