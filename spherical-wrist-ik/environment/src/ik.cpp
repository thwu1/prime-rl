#include "manipulator.h"


namespace manipulator {

int inverse(const double* T, double* q_sols, double q6_des) {
    // TODO: implement analytic inverse kinematics for this manipulator.
    //
    // The forward() function in fk.cpp computes:
    //   T_base_ee = T_base_0 * T_0_6(q) * T_6_ee
    //
    // Your implementation must invert this mapping: given T_base_ee,
    // recover all valid joint-angle vectors q such that forward(q)
    // reproduces the input pose.
    (void)T;
    (void)q_sols;
    (void)q6_des;
    return 0;
}

} // namespace manipulator
