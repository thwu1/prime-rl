/*
 * Ground truth generator for CPI preintegration models.
 * Reads IMU data and sensor config, runs both Model 1 and Model 2,
 * and writes JSON ground truth files.
 */

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
    std::getline(file, line);  // skip header
    while (std::getline(file, line)) {
        std::istringstream iss(line);
        std::string tok;
        ImuSample s;
        std::getline(iss, tok, ',');  // seq_id
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
        << cpi.q_k2tau(3) << "]\n";
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

    // Model 2
    ov_core::CpiV2 v2(sigma_w, sigma_wb, sigma_a, sigma_ab);
    v2.setLinearizationPoints(b_w, b_a);
    for (size_t i = 0; i + 1 < samples.size(); i++) {
        v2.feed_IMU(samples[i].timestamp, samples[i+1].timestamp,
                    samples[i].gyro, samples[i].accel);
    }
    write_json("/app/output/groundtruth_v2.json", v2);

    std::cout << "Done" << std::endl;
    return 0;
}
