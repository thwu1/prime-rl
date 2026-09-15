/*
 * Time integrator for constrained multibody systems modeled as index-3 DAEs.
 *
 * Solves:   M * a  +  Phi_q(q)^T * lambda  =  F(t, q, v)
 *           Phi(q) = 0
 *
 * using an implicit Newmark-family scheme with generalized-alpha weighting
 * for controllable numerical dissipation.
 */

#include "integrator.h"
#include <fstream>
#include <iostream>
#include <cmath>

Integrator::Integrator(DoublePendulum& model, double rho_inf, double h,
                       double newton_tol, int max_iter)
    : model_(model), h_(h), newton_tol_(newton_tol), max_iter_(max_iter)
{
    alpha_m_ = (2.0 * rho_inf - 1.0) / (rho_inf + 1.0);
    alpha_f_ = rho_inf / (rho_inf + 1.0);
    gamma_N_ = 0.5 - alpha_m_ + alpha_f_;
    beta_N_  = 0.25 * (gamma_N_ + 0.5) * (gamma_N_ + 0.5);
}

void Integrator::computeInitialAccelerations(
    const Eigen::VectorXd& q0, const Eigen::VectorXd& v0,
    Eigen::VectorXd& a0, Eigen::VectorXd& lam0)
{
    int nq = model_.nq();
    int nc = model_.nc();
    Eigen::MatrixXd M   = model_.massMatrix();
    Eigen::VectorXd F   = model_.forces(0.0, q0, v0);
    Eigen::MatrixXd Cq  = model_.constraintJacobian(q0);
    Eigen::VectorXd gam = model_.gamma(q0, v0);

    Eigen::MatrixXd A = Eigen::MatrixXd::Zero(nq + nc, nq + nc);
    A.topLeftCorner(nq, nq) = M;
    A.topRightCorner(nq, nc) = Cq.transpose();
    A.bottomLeftCorner(nc, nq) = Cq;

    Eigen::VectorXd rhs = Eigen::VectorXd::Zero(nq + nc);
    rhs.head(nq) = F;
    rhs.tail(nc) = gam;

    Eigen::VectorXd sol = A.fullPivLu().solve(rhs);
    a0   = sol.head(nq);
    lam0 = sol.tail(nc);
}

void Integrator::step(double& t, Eigen::VectorXd& q, Eigen::VectorXd& v,
                      Eigen::VectorXd& a, Eigen::VectorXd& lam)
{
    int nq = model_.nq();
    int nc = model_.nc();
    double h    = h_;
    double beta = beta_N_;
    double gN   = gamma_N_;
    double am   = alpha_m_;
    double af   = alpha_f_;
    Eigen::MatrixXd M = model_.massMatrix();

    Eigen::VectorXd a_new   = a;
    Eigen::VectorXd lam_new = lam;
    Eigen::VectorXd q_old   = q;
    Eigen::VectorXd v_old   = v;

    for (int k = 0; k < max_iter_; k++) {
        // Newmark update formulas
        Eigen::VectorXd q_new = q_old + h * v_old
                                + h*h * ((0.5 - beta) * a + beta * a_new);
        Eigen::VectorXd v_new = v_old + h * ((1.0 - gN) * a + gN * a_new);

        // Weighted quantities for the alpha scheme
        Eigen::VectorXd a_am = (1.0 - am) * a_new + am * a;
        Eigen::VectorXd q_af = (1.0 - af) * q_new + af * q_old;
        Eigen::VectorXd v_af = (1.0 - af) * v_new + af * v_old;
        double t_af = t + (1.0 - af) * h;

        // Model evaluation
        Eigen::VectorXd Phi       = model_.constraints(q_new);
        Eigen::MatrixXd Phi_q_dyn = model_.constraintJacobian(q_new);
        Eigen::MatrixXd Phi_q_con = model_.constraintJacobian(q_new);
        Eigen::VectorXd F_af      = model_.forces(t_af, q_af, v_af);

        // Assemble residual
        Eigen::VectorXd R_dyn = M * a_am
                                + Phi_q_dyn.transpose() * lam_new - F_af;
        Eigen::VectorXd R(nq + nc);
        R.head(nq) = R_dyn;
        R.tail(nc) = Phi;

        if (R.norm() < newton_tol_) break;

        // Assemble tangent matrix
        Eigen::MatrixXd J = Eigen::MatrixXd::Zero(nq + nc, nq + nc);
        J.topLeftCorner(nq, nq) = M;
        J.topRightCorner(nq, nc) = Phi_q_dyn.transpose();
        J.bottomLeftCorner(nc, nq) = h*h * beta * Phi_q_con;

        Eigen::VectorXd delta = J.fullPivLu().solve(-R);
        a_new   += delta.head(nq);
        lam_new += delta.tail(nc);
    }

    q = q_old + h * v_old + h*h * ((0.5 - beta) * a + beta * a_new);
    v = v_old + h * ((1.0 - gN) * a + gN * a_new);
    a   = a_new;
    lam = lam_new;
    t  += h;
}

SimResult Integrator::simulate(double t_end, Eigen::VectorXd q0,
                                Eigen::VectorXd v0, int output_interval)
{
    SimResult result;
    Eigen::VectorXd a0, lam0;
    computeInitialAccelerations(q0, v0, a0, lam0);

    double t = 0.0;
    Eigen::VectorXd q = q0, v = v0, a = a0, lam = lam0;

    result.time.push_back(t);
    result.positions.push_back(q);
    result.velocities.push_back(v);
    result.constraint_violations.push_back(model_.constraints(q).norm());
    result.energies.push_back(model_.totalEnergy(q, v));

    int n_steps = static_cast<int>(std::round(t_end / h_));
    for (int i = 1; i <= n_steps; i++) {
        step(t, q, v, a, lam);
        if (i % output_interval == 0) {
            result.time.push_back(t);
            result.positions.push_back(q);
            result.velocities.push_back(v);
            result.constraint_violations.push_back(
                model_.constraints(q).norm());
            result.energies.push_back(model_.totalEnergy(q, v));
        }
    }
    return result;
}

void Integrator::writeCSV(const std::string& filename,
                           const SimResult& result)
{
    std::ofstream ofs(filename);
    ofs << "time,x1,y1,theta1,x2,y2,theta2,"
        << "vx1,vy1,omega1,vx2,vy2,omega2,"
        << "constraint_violation,total_energy\n";
    ofs << std::scientific;
    ofs.precision(12);
    for (size_t i = 0; i < result.time.size(); i++) {
        ofs << result.time[i];
        for (int j = 0; j < 6; j++)
            ofs << "," << result.positions[i](j);
        for (int j = 0; j < 6; j++)
            ofs << "," << result.velocities[i](j);
        ofs << "," << result.constraint_violations[i];
        ofs << "," << result.energies[i];
        ofs << "\n";
    }
    ofs.close();
}
