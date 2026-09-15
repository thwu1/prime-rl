
#include "point_cloud.hpp"
#include "registration.hpp"
#include <iostream>
#include <iomanip>

int main(int argc, char** argv)
{
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0]
                  << " <source.pcd> <target.pcd>" << std::endl;
        return 1;
    }

    PointCloud source, target;

    if (!source.loadPCD(argv[1])) {
        std::cerr << "Failed to load " << argv[1] << std::endl;
        return 1;
    }
    if (!target.loadPCD(argv[2])) {
        std::cerr << "Failed to load " << argv[2] << std::endl;
        return 1;
    }

    std::cerr << "Source: " << source.size() << " points" << std::endl;
    std::cerr << "Target: " << target.size() << " points" << std::endl;

    auto result = alignPointToPlane(source, target, 100, 0.5f, 1e-6f);

    std::cerr << "Iterations: " << result.iterations << std::endl;
    std::cerr << "Converged:  " << (result.converged ? "yes" : "no") << std::endl;
    std::cerr << "Fitness:    " << result.fitness_score << std::endl;

    // Print 4x4 transformation matrix to stdout (machine-readable)
    std::cout << std::fixed << std::setprecision(10);
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) {
            if (j > 0) std::cout << " ";
            std::cout << result.transformation(i, j);
        }
        std::cout << "\n";
    }

    // Print summary metrics
    std::cout << "FITNESS " << result.fitness_score << "\n";
    std::cout << "CONVERGED " << (result.converged ? 1 : 0) << "\n";
    std::cout << "ITERATIONS " << result.iterations << "\n";

    return 0;
}
