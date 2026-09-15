#pragma once
#include <Eigen/Dense>
#include <vector>
#include <string>
#include "pendulum.h"

struct SimResult {
    std::vector<double> time;
    std::vector<Eigen::VectorXd> positions;
    std::vector<Eigen::VectorXd> velocities;
    std::vector<double> constraint_violations;
    std::vector<double> energies;
};

class Integrator {
public:
    Integrator(DoublePendulum& model, double rho_inf, double h,
               double newton_tol = 1e-10, int max_iter = 50);

    void computeInitialAccelerations(const Eigen::VectorXd& q0,
                                      const Eigen::VectorXd& v0,
                                      Eigen::VectorXd& a0,
                                      Eigen::VectorXd& lam0);

    void step(double& t, Eigen::VectorXd& q, Eigen::VectorXd& v,
              Eigen::VectorXd& a, Eigen::VectorXd& lam);

    SimResult simulate(double t_end, Eigen::VectorXd q0,
                       Eigen::VectorXd v0, int output_interval = 1);

    static void writeCSV(const std::string& filename,
                         const SimResult& result);

private:
    DoublePendulum& model_;
    double h_, newton_tol_;
    int max_iter_;
    double alpha_m_, alpha_f_, beta_N_, gamma_N_;
};
