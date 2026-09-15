#include "pendulum.h"
#include <cmath>

DoublePendulum::DoublePendulum(double L1, double L2,
                               double m1, double m2, double g)
    : L1_(L1), L2_(L2), m1_(m1), m2_(m2), g_(g),
      I1_(m1 * L1 * L1 / 12.0), I2_(m2 * L2 * L2 / 12.0) {}

Eigen::MatrixXd DoublePendulum::massMatrix() const {
    Eigen::MatrixXd M = Eigen::MatrixXd::Zero(6, 6);
    M(0, 0) = m1_;  M(1, 1) = m1_;  M(2, 2) = I1_;
    M(3, 3) = m2_;  M(4, 4) = m2_;  M(5, 5) = I2_;
    return M;
}

Eigen::VectorXd DoublePendulum::forces(double /*t*/,
                                        const Eigen::VectorXd& /*q*/,
                                        const Eigen::VectorXd& /*v*/) const {
    Eigen::VectorXd F = Eigen::VectorXd::Zero(6);
    F(1) = -m1_ * g_;
    F(4) = -m2_ * g_;
    return F;
}

Eigen::VectorXd DoublePendulum::constraints(const Eigen::VectorXd& q) const {
    double x1 = q(0), y1 = q(1), t1 = q(2);
    double x2 = q(3), y2 = q(4), t2 = q(5);
    Eigen::VectorXd Phi(4);
    Phi(0) = x1 - (L1_ / 2.0) * std::cos(t1);
    Phi(1) = y1 - (L1_ / 2.0) * std::sin(t1);
    Phi(2) = x1 + (L1_ / 2.0) * std::cos(t1) - x2 + (L2_ / 2.0) * std::cos(t2);
    Phi(3) = y1 + (L1_ / 2.0) * std::sin(t1) - y2 + (L2_ / 2.0) * std::sin(t2);
    return Phi;
}

Eigen::MatrixXd DoublePendulum::constraintJacobian(
    const Eigen::VectorXd& q) const {
    double t1 = q(2), t2 = q(5);
    Eigen::MatrixXd Phi_q = Eigen::MatrixXd::Zero(4, 6);
    Phi_q(0, 0) = 1.0;
    Phi_q(0, 2) = (L1_ / 2.0) * std::sin(t1);
    Phi_q(1, 1) = 1.0;
    Phi_q(1, 2) = -(L1_ / 2.0) * std::cos(t1);
    Phi_q(2, 0) = 1.0;
    Phi_q(2, 2) = -(L1_ / 2.0) * std::sin(t1);
    Phi_q(2, 3) = -1.0;
    Phi_q(2, 5) = -(L2_ / 2.0) * std::sin(t2);
    Phi_q(3, 1) = 1.0;
    Phi_q(3, 2) = (L1_ / 2.0) * std::cos(t1);
    Phi_q(3, 4) = -1.0;
    Phi_q(3, 5) = (L2_ / 2.0) * std::cos(t2);
    return Phi_q;
}

Eigen::VectorXd DoublePendulum::gamma(const Eigen::VectorXd& q,
                                       const Eigen::VectorXd& v) const {
    double t1 = q(2), t2 = q(5);
    double vt1 = v(2), vt2 = v(5);
    Eigen::VectorXd gam(4);
    gam(0) = (L1_ / 2.0) * std::cos(t1) * vt1 * vt1;
    gam(1) = (L1_ / 2.0) * std::sin(t1) * vt1 * vt1;
    gam(2) = -(L1_ / 2.0) * std::cos(t1) * vt1 * vt1
             - (L2_ / 2.0) * std::cos(t2) * vt2 * vt2;
    gam(3) = -(L1_ / 2.0) * std::sin(t1) * vt1 * vt1
             - (L2_ / 2.0) * std::sin(t2) * vt2 * vt2;
    return gam;
}

void DoublePendulum::consistentIC(double theta1, double theta2,
                                   double omega1, double omega2,
                                   Eigen::VectorXd& q0,
                                   Eigen::VectorXd& v0) const {
    q0.resize(6);
    v0.resize(6);
    double x1 = (L1_ / 2.0) * std::cos(theta1);
    double y1 = (L1_ / 2.0) * std::sin(theta1);
    double tip_x = L1_ * std::cos(theta1);
    double tip_y = L1_ * std::sin(theta1);
    double x2 = tip_x + (L2_ / 2.0) * std::cos(theta2);
    double y2 = tip_y + (L2_ / 2.0) * std::sin(theta2);
    q0 << x1, y1, theta1, x2, y2, theta2;

    double vx1 = -(L1_ / 2.0) * std::sin(theta1) * omega1;
    double vy1 =  (L1_ / 2.0) * std::cos(theta1) * omega1;
    double vx2 = -L1_ * std::sin(theta1) * omega1
                 - (L2_ / 2.0) * std::sin(theta2) * omega2;
    double vy2 =  L1_ * std::cos(theta1) * omega1
                 + (L2_ / 2.0) * std::cos(theta2) * omega2;
    v0 << vx1, vy1, omega1, vx2, vy2, omega2;
}

double DoublePendulum::totalEnergy(const Eigen::VectorXd& q,
                                    const Eigen::VectorXd& v) const {
    Eigen::MatrixXd M = massMatrix();
    double KE = 0.5 * v.dot(M * v);
    double PE = m1_ * g_ * q(1) + m2_ * g_ * q(4);
    return KE + PE;
}
