
#include <nlohmann/json.hpp>
#include <fstream>
#include <iostream>
#include "histogram_scanner.hpp"

using json = nlohmann::json;

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
    config.path_smooth = j.value("path_smooth", 0.0);
    config.scan_reverse = j.value("scan_reverse", false);
    config.has_na_bin = j.value("has_na_bin", false);
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

    auto process = [&](const json& tc) {
        SplitConfig config = parse_config(tc);
        SplitResult res = FindBestSplit(config);
        output.push_back({
            {"best_threshold", res.best_threshold},
            {"best_gain", res.best_gain},
            {"left_output", res.left_output},
            {"right_output", res.right_output},
            {"left_count", res.left_count},
            {"right_count", res.right_count},
            {"default_left", res.default_left}
        });
    };

    if (input.contains("test_cases")) {
        for (auto& tc : input["test_cases"]) {
            process(tc);
        }
    } else {
        process(input);
    }

    std::ofstream outfile("/app/output.json");
    outfile << output.dump(2) << std::endl;
    outfile.close();
    return 0;
}
