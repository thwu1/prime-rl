#pragma once
#include <Eigen/Dense>

class DoublePendulum {
public:
    DoublePendulum(double L1 = 1.0, double L2 = 1.0,
                   double m1 = 1.0, double m2 = 1.0, double g = 9.81);
    int nq() const { return 6; }
    int nc() const { return 4; }
    double getL1() const { return L1_; }
    double getL2() const { return L2_; }
    double getM1() const { return m1_; }
    double getM2() const { return m2_; }
    double getG()  const { return g_; }

    Eigen::MatrixXd massMatrix() const;
    Eigen::VectorXd forces(double t, const Eigen::VectorXd& q,
                           const Eigen::VectorXd& v) const;
    Eigen::VectorXd constraints(const Eigen::VectorXd& q) const;
    Eigen::MatrixXd constraintJacobian(const Eigen::VectorXd& q) const;
    Eigen::VectorXd gamma(const Eigen::VectorXd& q,
                          const Eigen::VectorXd& v) const;
    void consistentIC(double theta1, double theta2,
                      double omega1, double omega2,
                      Eigen::VectorXd& q0, Eigen::VectorXd& v0) const;
    double totalEnergy(const Eigen::VectorXd& q,
                       const Eigen::VectorXd& v) const;
private:
    double L1_, L2_, m1_, m2_, g_, I1_, I2_;
};
