#!/bin/bash

set -e

# Fix CMakeLists.txt: correct the epsilon value from 1e-3 to 1e-15
sed -i 's/set(NUMERIC_EPSILON "1e-3"/set(NUMERIC_EPSILON "1e-15"/' /app/CMakeLists.txt

# Write the corrected split_math.hpp
cat > /app/split_math.hpp << 'CPPEOF'
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

inline double ThresholdL1(double s, double l1) {
    double reg_s = std::max(0.0, std::fabs(s) - l1);
    return Sign(s) * reg_s;
}

inline double CalculateLeafOutput(double sum_grad, double sum_hess,
                                   double l1, double l2,
                                   double max_delta_step,
                                   double constraint_min, double constraint_max,
                                   bool use_constraints,
                                   double smoothing, int num_data,
                                   double parent_output) {
    double sg = ThresholdL1(sum_grad, l1);
    double output = -sg / (sum_hess + l2);
    if (max_delta_step > 0 && std::fabs(output) > max_delta_step) {
        output = Sign(output) * max_delta_step;
    }
    if (smoothing > kEpsilon) {
        double ratio = static_cast<double>(num_data) / smoothing;
        output = output * ratio / (ratio + 1.0) + parent_output / (ratio + 1.0);
    }
    if (use_constraints) {
        output = std::max(constraint_min, std::min(constraint_max, output));
    }
    return output;
}

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
        double output = CalculateLeafOutput(sum_grad, sum_hess, l1, l2,
                                            max_delta_step, constraint_min,
                                            constraint_max, use_constraints,
                                            smoothing, num_data, parent_output);
        double sg = ThresholdL1(sum_grad, l1);
        return -(2.0 * sg * output + (sum_hess + l2) * output * output);
    }
}

inline double GetLeafGainGivenOutput(double sum_grad, double sum_hess,
                                      double l1, double l2, double output) {
    double sg = ThresholdL1(sum_grad, l1);
    return -(2.0 * sg * output + (sum_hess + l2) * output * output);
}
CPPEOF

# Write the corrected histogram_scanner.hpp
cat > /app/histogram_scanner.hpp << 'CPPEOF'
#pragma once

#include "split_math.hpp"
#include <vector>
#include <cmath>

struct BinData {
    double grad;
    double hess;
};

struct SplitConfig {
    std::vector<BinData> bins;
    double total_gradient;
    double total_hessian;
    int total_count;
    double lambda_l1;
    double lambda_l2;
    int min_data_in_leaf;
    double min_sum_hessian_in_leaf;
    double min_gain_to_split;
    double max_delta_step;
    int monotone_type;
    double constraint_min;
    double constraint_max;
    double parent_output;
    double path_smooth;
    bool scan_reverse;
    bool has_na_bin;
};

struct SplitResult {
    int best_threshold = -1;
    double best_gain = 0.0;
    double left_output = 0.0;
    double right_output = 0.0;
    int left_count = 0;
    int right_count = 0;
    bool default_left = false;
};

inline SplitResult FindBestSplitForward(const SplitConfig& config) {
    SplitResult result;
    result.default_left = false;
    int num_bins = static_cast<int>(config.bins.size());
    if (num_bins <= 1) return result;

    bool use_mc = (config.monotone_type != 0);
    double cnt_factor = static_cast<double>(config.total_count) / config.total_hessian;

    double parent_gain = GetLeafGain(config.total_gradient,
                                     config.total_hessian + 2 * kEpsilon,
                                     config.lambda_l1, config.lambda_l2,
                                     config.max_delta_step,
                                     config.constraint_min, config.constraint_max,
                                     use_mc, config.path_smooth,
                                     config.total_count, config.parent_output);
    double min_gain_shift = parent_gain + config.min_gain_to_split;

    double sum_left_grad = 0.0;
    double sum_left_hess = kEpsilon;
    int left_count = 0;

    double best_gain = kMinScore;

    for (int t = 0; t < num_bins - 1; ++t) {
        int bin_idx = t + 1;
        if (bin_idx >= num_bins) break;

        sum_left_grad += config.bins[bin_idx].grad;
        sum_left_hess += config.bins[bin_idx].hess;
        left_count += static_cast<int>(std::round(
            config.bins[bin_idx].hess * cnt_factor));

        if (left_count < config.min_data_in_leaf) continue;
        if (sum_left_hess < config.min_sum_hessian_in_leaf) continue;

        int right_count = config.total_count - left_count;
        if (right_count < config.min_data_in_leaf) break;

        double sum_right_grad = config.total_gradient - sum_left_grad;
        double sum_right_hess = config.total_hessian - sum_left_hess;
        if (sum_right_hess < config.min_sum_hessian_in_leaf) break;

        double current_gain;

        if (use_mc) {
            double left_out = CalculateLeafOutput(
                sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, true,
                config.path_smooth, left_count, config.parent_output);
            double right_out = CalculateLeafOutput(
                sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, true,
                config.path_smooth, right_count, config.parent_output);

            if (config.monotone_type > 0 && left_out > right_out) continue;
            if (config.monotone_type < 0 && left_out < right_out) continue;

            current_gain = GetLeafGainGivenOutput(
                sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2, left_out) +
                GetLeafGainGivenOutput(
                sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2, right_out);
        } else {
            current_gain = GetLeafGain(sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, false,
                config.path_smooth, left_count, config.parent_output) +
                GetLeafGain(sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, false,
                config.path_smooth, right_count, config.parent_output);
        }

        if (current_gain <= min_gain_shift) continue;

        if (current_gain > best_gain) {
            best_gain = current_gain;
            double net_gain = current_gain - min_gain_shift;

            double l_out = CalculateLeafOutput(
                sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, use_mc,
                config.path_smooth, left_count, config.parent_output);
            double r_out = CalculateLeafOutput(
                sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, use_mc,
                config.path_smooth, right_count, config.parent_output);

            result.best_threshold = t;
            result.best_gain = net_gain;
            result.left_output = l_out;
            result.right_output = r_out;
            result.left_count = left_count;
            result.right_count = right_count;
        }
    }

    if (best_gain <= kMinScore) return SplitResult{};
    return result;
}

inline SplitResult FindBestSplitReverse(const SplitConfig& config) {
    SplitResult result;
    result.default_left = true;
    int num_bins = static_cast<int>(config.bins.size());
    if (num_bins <= 1) return result;

    bool use_mc = (config.monotone_type != 0);
    double cnt_factor = static_cast<double>(config.total_count) / config.total_hessian;

    double parent_gain = GetLeafGain(config.total_gradient,
                                     config.total_hessian + 2 * kEpsilon,
                                     config.lambda_l1, config.lambda_l2,
                                     config.max_delta_step,
                                     config.constraint_min, config.constraint_max,
                                     use_mc, config.path_smooth,
                                     config.total_count, config.parent_output);
    double min_gain_shift = parent_gain + config.min_gain_to_split;

    double sum_right_grad = 0.0;
    double sum_right_hess = kEpsilon;
    int right_count = 0;

    double best_gain = kMinScore;

    int t_start = num_bins - 1;
    if (config.has_na_bin) t_start -= 1;
    int t_end = 1;

    for (int t = t_start; t >= t_end; --t) {
        sum_right_grad += config.bins[t].grad;
        sum_right_hess += config.bins[t].hess;
        right_count += static_cast<int>(std::round(
            config.bins[t].hess * cnt_factor));

        if (right_count < config.min_data_in_leaf) continue;
        if (sum_right_hess < config.min_sum_hessian_in_leaf) continue;

        int left_count = config.total_count - right_count;
        if (left_count < config.min_data_in_leaf) break;

        double sum_left_grad = config.total_gradient - sum_right_grad;
        double sum_left_hess = config.total_hessian - sum_right_hess;
        if (sum_left_hess < config.min_sum_hessian_in_leaf) break;

        double current_gain;

        if (use_mc) {
            double left_out = CalculateLeafOutput(
                sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, true,
                config.path_smooth, left_count, config.parent_output);
            double right_out = CalculateLeafOutput(
                sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, true,
                config.path_smooth, right_count, config.parent_output);

            if (config.monotone_type > 0 && left_out > right_out) continue;
            if (config.monotone_type < 0 && left_out < right_out) continue;

            current_gain = GetLeafGainGivenOutput(
                sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2, left_out) +
                GetLeafGainGivenOutput(
                sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2, right_out);
        } else {
            current_gain = GetLeafGain(sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, false,
                config.path_smooth, left_count, config.parent_output) +
                GetLeafGain(sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, false,
                config.path_smooth, right_count, config.parent_output);
        }

        if (current_gain <= min_gain_shift) continue;

        if (current_gain > best_gain) {
            best_gain = current_gain;
            double net_gain = current_gain - min_gain_shift;

            double l_out = CalculateLeafOutput(
                sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, use_mc,
                config.path_smooth, left_count, config.parent_output);
            double r_out = CalculateLeafOutput(
                sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, use_mc,
                config.path_smooth, right_count, config.parent_output);

            result.best_threshold = t - 1;
            result.best_gain = net_gain;
            result.left_output = l_out;
            result.right_output = r_out;
            result.left_count = left_count;
            result.right_count = right_count;
        }
    }

    if (best_gain <= kMinScore) return SplitResult{};
    return result;
}

inline SplitResult FindBestSplit(const SplitConfig& config) {
    if (config.scan_reverse) return FindBestSplitReverse(config);
    return FindBestSplitForward(config);
}
CPPEOF

# Rebuild with cmake
cd /app && rm -rf build && cmake -B build && cmake --build build
