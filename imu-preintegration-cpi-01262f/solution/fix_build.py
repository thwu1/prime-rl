
"""
Fix the broken CMake build and incomplete C++ ground truth generator.

Issues fixed:
1. CMakeLists.txt: missing CpiV2.cpp source, missing Eigen3 linking
2. generate_groundtruth.cpp: V2 missing q_k_lin/grav linearization,
   JSON output missing P_meas_trace and P_meas_diag
"""

import os

# Fix CMakeLists.txt
cmake_path = '/app/reference/CMakeLists.txt'
cmake_content = """cmake_minimum_required(VERSION 3.10)
project(cpi_groundtruth CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Eigen3 REQUIRED)

include_directories(${CMAKE_SOURCE_DIR})

add_executable(generate_groundtruth
    generate_groundtruth.cpp
    cpi/CpiV1.cpp
    cpi/CpiV2.cpp
)

target_link_libraries(generate_groundtruth Eigen3::Eigen)
"""

with open(cmake_path, 'w') as f:
    f.write(cmake_content)

# Fix generate_groundtruth.cpp
gt_path = '/app/reference/generate_groundtruth.cpp'
gt_content = r"""
#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <iomanip>
#include "cpi/CpiV1.h"
#include "cpi/CpiV2.h"

struct ImuSample {
    double timestamp;
    Eigen::Vector3d gyro;
    Eigen::Vector3d accel;
};

std::vector<ImuSample> read_csv(const std::string& path) {
    std::vector<ImuSample> samples;
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "Cannot open: " << path << std::endl;
        return samples;
    }
    std::string line;
    std::getline(file, line);
    while (std::getline(file, line)) {
        std::istringstream iss(line);
        std::string tok;
        ImuSample s;
        std::getline(iss, tok, ',');
        std::getline(iss, tok, ','); s.timestamp = std::stod(tok) * 1e-9;
        std::getline(iss, tok, ','); s.gyro(0) = std::stod(tok);
        std::getline(iss, tok, ','); s.gyro(1) = std::stod(tok);
        std::getline(iss, tok, ','); s.gyro(2) = std::stod(tok);
        std::getline(iss, tok, ','); s.accel(0) = std::stod(tok);
        std::getline(iss, tok, ','); s.accel(1) = std::stod(tok);
        std::getline(iss, tok, ','); s.accel(2) = std::stod(tok);
        samples.push_back(s);
    }
    return samples;
}

void write_json(const std::string& path, const ov_core::CpiBase& cpi) {
    std::ofstream out(path);
    out << std::setprecision(17);
    out << "{\n";
    out << "  \"DT\": " << cpi.DT << ",\n";
    out << "  \"alpha_tau\": [" << cpi.alpha_tau(0) << ", "
        << cpi.alpha_tau(1) << ", " << cpi.alpha_tau(2) << "],\n";
    out << "  \"beta_tau\": [" << cpi.beta_tau(0) << ", "
        << cpi.beta_tau(1) << ", " << cpi.beta_tau(2) << "],\n";
    out << "  \"q_k2tau\": [" << cpi.q_k2tau(0) << ", "
        << cpi.q_k2tau(1) << ", " << cpi.q_k2tau(2) << ", "
        << cpi.q_k2tau(3) << "],\n";
    out << "  \"P_meas_trace\": " << cpi.P_meas.trace() << ",\n";
    out << "  \"P_meas_diag\": [";
    for (int i = 0; i < 15; i++) {
        if (i > 0) out << ", ";
        out << cpi.P_meas(i, i);
    }
    out << "]\n";
    out << "}\n";
    out.close();
}

int main() {
    auto samples = read_csv("/app/data/imu_sequence.csv");
    if (samples.empty()) {
        std::cerr << "No samples loaded" << std::endl;
        return 1;
    }

    double sigma_w = 0.003, sigma_wb = 0.0001;
    double sigma_a = 0.01, sigma_ab = 0.001;
    Eigen::Vector3d b_w(0.015, -0.008, 0.005);
    Eigen::Vector3d b_a(0.04, -0.025, 0.015);

    // Model 1
    ov_core::CpiV1 v1(sigma_w, sigma_wb, sigma_a, sigma_ab);
    v1.setLinearizationPoints(b_w, b_a);
    for (size_t i = 0; i + 1 < samples.size(); i++) {
        v1.feed_IMU(samples[i].timestamp, samples[i+1].timestamp,
                    samples[i].gyro, samples[i].accel);
    }
    write_json("/app/output/groundtruth_v1.json", v1);

    // Model 2 with orientation linearization
    ov_core::CpiV2 v2(sigma_w, sigma_wb, sigma_a, sigma_ab);
    Eigen::Vector4d q_k_lin(0.0, 0.0, 0.0, 1.0);
    Eigen::Vector3d grav(0.0, 0.0, 9.81);
    v2.setLinearizationPoints(b_w, b_a, q_k_lin, grav);
    for (size_t i = 0; i + 1 < samples.size(); i++) {
        v2.feed_IMU(samples[i].timestamp, samples[i+1].timestamp,
                    samples[i].gyro, samples[i].accel);
    }
    write_json("/app/output/groundtruth_v2.json", v2);

    std::cout << "Done" << std::endl;
    return 0;
}
"""

with open(gt_path, 'w') as f:
    f.write(gt_content)

print("Build files fixed successfully")
