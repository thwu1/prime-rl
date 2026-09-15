#pragma once

#include <Eigen/Dense>
#include <vector>
#include <string>

struct PointCloud {
    std::vector<Eigen::Vector3f> points;

    bool loadPCD(const std::string& filename);
    std::size_t size() const { return points.size(); }
};
