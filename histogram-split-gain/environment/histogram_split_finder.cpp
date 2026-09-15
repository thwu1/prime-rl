
#include <nlohmann/json.hpp>
#include <iostream>
#include <fstream>
#include <vector>
#include <cmath>
#include <algorithm>
#include <limits>

using json = nlohmann::json;

static constexpr double kEpsilon = 1e-15;
static constexpr double kMinScore = -std::numeric_limits<double>::infinity();

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
};

struct SplitResult {
    int best_threshold = -1;
    double best_gain = 0.0;
    double left_output = 0.0;
    double right_output = 0.0;
    int left_count = 0;
    int right_count = 0;
};

static inline double Sign(double x) {
    if (x > 0) return 1.0;
    if (x < 0) return -1.0;
    return 0.0;
}

// Apply L1 soft-thresholding to gradient sum
double ThresholdL1(double s, double l1) {
    if (std::fabs(s) <= l1) {
        return 0.0;
    }
    return s;
}

// Compute optimal leaf output for a node
double CalculateLeafOutput(double sum_grad, double sum_hess,
                           double l1, double l2,
                           double max_delta_step,
                           double constraint_min, double constraint_max,
                           bool use_constraints) {
    double sg = ThresholdL1(sum_grad, l1);
    double output = -sg / (sum_hess + l2);
    return output;
}

// Compute the gain contribution of a leaf node
double GetLeafGain(double sum_grad, double sum_hess,
                   double l1, double l2,
                   double max_delta_step,
                   double constraint_min, double constraint_max,
                   bool use_constraints) {
    double sg = ThresholdL1(sum_grad, l1);
    if (max_delta_step <= 0 && !use_constraints) {
        return (sg * sg) / (sum_hess + l2);
    }
    double output = -sg / (sum_hess + l2);
    return -(2.0 * sg * output + (sum_hess + l2) * output * output);
}

// Find the best split threshold by scanning bins left-to-right
SplitResult FindBestSplit(const SplitConfig& config) {
    SplitResult result;
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
                                       config.lambda_l1, config.lambda_l2,
                                       config.max_delta_step,
                                       config.constraint_min, config.constraint_max,
                                       false);
        double right_gain = GetLeafGain(sum_right_grad, sum_right_hess,
                                        config.lambda_l1, config.lambda_l2,
                                        config.max_delta_step,
                                        config.constraint_min, config.constraint_max,
                                        false);

        double current_gain = left_gain + right_gain;

        if (current_gain > best_gain) {
            best_gain = current_gain;
            result.best_threshold = t;
            result.best_gain = current_gain;
            result.left_count = left_count;
            result.right_count = right_count;
            result.left_output = CalculateLeafOutput(
                sum_left_grad, sum_left_hess,
                config.lambda_l1, config.lambda_l2,
                config.max_delta_step,
                config.constraint_min, config.constraint_max, false);
            result.right_output = CalculateLeafOutput(
                sum_right_grad, sum_right_hess,
                config.lambda_l1, config.lambda_l2,
                config.max_delta_step,
                config.constraint_min, config.constraint_max, false);
        }
    }

    if (best_gain <= kMinScore) {
        result = SplitResult{};
    }
    return result;
}

SplitConfig parse_config(const json& j) {
    SplitConfig config;
    for (auto& b : j["bins"]) {
        config.bins.push_back({b["grad"].get<double>(), b["hess"].get<double>()});
    }
    config.total_gradient = j["total_gradient"].get<double>();
    config.total_hessian = j["total_hessian"].get<double>();
    config.total_count = j["total_count"].get<int>();
    config.lambda_l1 = j["lambda_l1"].get<double>();
    config.lambda_l2 = j["lambda_l2"].get<double>();
    config.min_data_in_leaf = j["min_data_in_leaf"].get<int>();
    config.min_sum_hessian_in_leaf = j["min_sum_hessian_in_leaf"].get<double>();
    config.min_gain_to_split = j["min_gain_to_split"].get<double>();
    config.max_delta_step = j["max_delta_step"].get<double>();
    config.monotone_type = j["monotone_type"].get<int>();
    config.constraint_min = j.value("constraint_min", -1e300);
    config.constraint_max = j.value("constraint_max", 1e300);
    config.parent_output = j.value("parent_output", 0.0);
    return config;
}

int main() {
    std::ifstream infile("/app/input.json");
    if (!infile.is_open()) {
        std::cerr << "Cannot open /app/input.json" << std::endl;
        return 1;
    }
    json input;
    infile >> input;
    infile.close();

    json output = json::array();

    if (input.contains("test_cases")) {
        for (auto& tc : input["test_cases"]) {
            SplitConfig config = parse_config(tc);
            SplitResult res = FindBestSplit(config);
            output.push_back({
                {"best_threshold", res.best_threshold},
                {"best_gain", res.best_gain},
                {"left_output", res.left_output},
                {"right_output", res.right_output},
                {"left_count", res.left_count},
                {"right_count", res.right_count}
            });
        }
    } else {
        SplitConfig config = parse_config(input);
        SplitResult res = FindBestSplit(config);
        output.push_back({
            {"best_threshold", res.best_threshold},
            {"best_gain", res.best_gain},
            {"left_output", res.left_output},
            {"right_output", res.right_output},
            {"left_count", res.left_count},
            {"right_count", res.right_count}
        });
    }

    std::ofstream outfile("/app/output.json");
    outfile << output.dump(2) << std::endl;
    outfile.close();

    return 0;
}
