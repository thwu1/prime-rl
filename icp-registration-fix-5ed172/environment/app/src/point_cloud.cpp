
#include "point_cloud.hpp"
#include <fstream>
#include <sstream>
#include <iostream>

bool PointCloud::loadPCD(const std::string& filename)
{
    std::ifstream file(filename);
    if (!file.is_open()) {
        std::cerr << "Cannot open " << filename << std::endl;
        return false;
    }

    std::string line;
    bool data_section = false;

    while (std::getline(file, line)) {
        if (!data_section) {
            if (line.size() >= 4 && line.substr(0, 4) == "DATA") {
                data_section = true;
            }
            continue;
        }
        std::istringstream iss(line);
        float x, y, z;
        if (iss >> x >> y >> z) {
            points.push_back(Eigen::Vector3f(x, y, z));
        }
    }
    return !points.empty();
}
