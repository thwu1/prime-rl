#include "pendulum.h"
#include "integrator.h"
#include <iostream>
#include <string>
#include <cstdlib>

int main(int argc, char* argv[])
{
    if (argc != 9) {
        std::cerr << "Usage: sim theta1 theta2 omega1 omega2"
                  << " rho_inf h t_end output_file\n";
        return 1;
    }

    double theta1  = std::stod(argv[1]);
    double theta2  = std::stod(argv[2]);
    double omega1  = std::stod(argv[3]);
    double omega2  = std::stod(argv[4]);
    double rho_inf = std::stod(argv[5]);
    double h       = std::stod(argv[6]);
    double t_end   = std::stod(argv[7]);
    std::string output_file = argv[8];

    DoublePendulum model;
    Eigen::VectorXd q0, v0;
    model.consistentIC(theta1, theta2, omega1, omega2, q0, v0);

    Integrator integ(model, rho_inf, h);
    SimResult result = integ.simulate(t_end, q0, v0);
    Integrator::writeCSV(output_file, result);

    std::cout << "Wrote " << result.time.size()
              << " steps to " << output_file << std::endl;
    return 0;
}
