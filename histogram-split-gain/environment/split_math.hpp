#pragma once

#include <cmath>
#include <algorithm>
#include <limits>

#ifndef SPLIT_EPSILON
#error "SPLIT_EPSILON must be defined via the build system"
#endif

static constexpr double kEpsilon = SPLIT_EPSILON;
static constexpr double kMinScore = -std::numeric_limits<double>::infinity();

inline double Sign(double x) {
    if (x > 0) return 1.0;
    if (x < 0) return -1.0;
    return 0.0;
}

// Apply L1 soft-thresholding to gradient sum.
// When |s| <= l1, gradient is fully absorbed by regularization.
// Otherwise, shrink toward zero by l1.
inline double ThresholdL1(double s, double l1) {
    if (std::fabs(s) <= l1) return 0.0;
    return s;
}

// Compute the optimal leaf output value given gradient/hessian sums
// and regularization, constraint, and smoothing parameters.
inline double CalculateLeafOutput(double sum_grad, double sum_hess,
                                   double l1, double l2,
                                   double max_delta_step,
                                   double constraint_min, double constraint_max,
                                   bool use_constraints,
                                   double smoothing, int num_data,
                                   double parent_output) {
    double sg = ThresholdL1(sum_grad, l1);
    double output = -sg / (sum_hess + l2);
    if (smoothing > kEpsilon) {
        output = output + parent_output;
    }
    return output;
}

// Compute the gain contribution of a single leaf node.
// For the simple case (no clamping/constraints/smoothing), gain = sg^2/(h+l2).
// Otherwise uses output-based formula: -(2*sg*out + (h+l2)*out^2).
inline double GetLeafGain(double sum_grad, double sum_hess,
                          double l1, double l2,
                          double max_delta_step,
                          double constraint_min, double constraint_max,
                          bool use_constraints,
                          double smoothing, int num_data,
                          double parent_output) {
    if (max_delta_step <= 0 && !use_constraints && smoothing <= kEpsilon) {
        double sg = ThresholdL1(sum_grad, l1);
        return (sg * sg) / (sum_hess + l2);
    } else {
        double sg = ThresholdL1(sum_grad, l1);
        double output = -sg / (sum_hess + l2);
        return -(2.0 * sg * output + (sum_hess + l2) * output * output);
    }
}

// Compute gain given a pre-computed leaf output value.
inline double GetLeafGainGivenOutput(double sum_grad, double sum_hess,
                                      double l1, double l2, double output) {
    double sg = ThresholdL1(sum_grad, l1);
    return -(2.0 * sg * output + (sum_hess + l2) * output * output);
}
