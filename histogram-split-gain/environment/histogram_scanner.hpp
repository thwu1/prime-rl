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

// Forward scan: accumulate stats left-to-right, bins 1..N-1
inline SplitResult FindBestSplitForward(const SplitConfig& config) {
    SplitResult result;
    result.default_left = false;
    int num_bins = static_cast<int>(config.bins.size());
    if (num_bins <= 1) return result;

    double cnt_factor = static_cast<double>(config.total_count) / config.total_hessian;

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
        double sum_right_grad = config.total_gradient - sum_left_grad;
        double sum_right_hess = config.total_hessian - sum_left_hess;

        double left_gain = GetLeafGain(sum_left_grad, sum_left_hess,
            config.lambda_l1, config.lambda_l2, config.max_delta_step,
            config.constraint_min, config.constraint_max, false,
            config.path_smooth, left_count, config.parent_output);
        double right_gain = GetLeafGain(sum_right_grad, sum_right_hess,
            config.lambda_l1, config.lambda_l2, config.max_delta_step,
            config.constraint_min, config.constraint_max, false,
            config.path_smooth, right_count, config.parent_output);
        double current_gain = left_gain + right_gain;

        if (current_gain > best_gain) {
            best_gain = current_gain;
            result.best_threshold = t;
            result.best_gain = current_gain;
            result.left_count = left_count;
            result.right_count = right_count;
            result.left_output = CalculateLeafOutput(
                sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, false,
                config.path_smooth, left_count, config.parent_output);
            result.right_output = CalculateLeafOutput(
                sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, false,
                config.path_smooth, right_count, config.parent_output);
        }
    }

    if (best_gain <= kMinScore) return SplitResult{};
    return result;
}

// Reverse scan: accumulate stats right-to-left, bins N-1..1
inline SplitResult FindBestSplitReverse(const SplitConfig& config) {
    SplitResult result;
    result.default_left = true;
    int num_bins = static_cast<int>(config.bins.size());
    if (num_bins <= 1) return result;

    double cnt_factor = static_cast<double>(config.total_count) / config.total_hessian;

    double sum_right_grad = 0.0;
    double sum_right_hess = kEpsilon;
    int right_count = 0;

    double best_gain = kMinScore;

    int t_start = num_bins - 1;
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

        double left_gain = GetLeafGain(sum_left_grad, sum_left_hess,
            config.lambda_l1, config.lambda_l2, config.max_delta_step,
            config.constraint_min, config.constraint_max, false,
            config.path_smooth, left_count, config.parent_output);
        double right_gain = GetLeafGain(sum_right_grad, sum_right_hess,
            config.lambda_l1, config.lambda_l2, config.max_delta_step,
            config.constraint_min, config.constraint_max, false,
            config.path_smooth, right_count, config.parent_output);
        double current_gain = left_gain + right_gain;

        if (current_gain > best_gain) {
            best_gain = current_gain;
            result.best_threshold = t;
            result.best_gain = current_gain;
            result.left_count = left_count;
            result.right_count = right_count;
            result.left_output = CalculateLeafOutput(
                sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, false,
                config.path_smooth, left_count, config.parent_output);
            result.right_output = CalculateLeafOutput(
                sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2, config.max_delta_step,
                config.constraint_min, config.constraint_max, false,
                config.path_smooth, right_count, config.parent_output);
        }
    }

    if (best_gain <= kMinScore) return SplitResult{};
    return result;
}

inline SplitResult FindBestSplit(const SplitConfig& config) {
    if (config.scan_reverse) return FindBestSplitReverse(config);
    return FindBestSplitForward(config);
}
