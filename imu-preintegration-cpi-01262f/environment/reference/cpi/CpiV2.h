#ifndef CPI_V2_H
#define CPI_V2_H

/*
 * MIT License
 * Copyright (c) 2018 Kevin Eckenhoff
 * Copyright (c) 2018 Patrick Geneva
 * Copyright (c) 2018 Guoquan Huang
 */

#include "CpiBase.h"

#include <Eigen/Dense>

namespace ov_core {

/**
 * @brief Model 2 of continuous preintegration.
 *
 * This model is the "piecewise constant local acceleration assumption."
 * Please see the following publication for details on the theory @cite Eckenhoff2019IJRR :
 * > Continuous Preintegration Theory for Graph-based Visual-Inertial Navigation
 * > Authors: Kevin Eckenhoff, Patrick Geneva, and Guoquan Huang
 * > http://udel.edu/~ghuang/papers/tr_cpi.pdf
 */
class CpiV2 : public CpiBase {

private:
  // Extended covariance used to handle the sampling model
  Eigen::Matrix<double, 21, 21> P_big = Eigen::Matrix<double, 21, 21>::Zero();

  // Our large compounded state transition Jacobian matrix
  Eigen::Matrix<double, 21, 21> Discrete_J_b = Eigen::Matrix<double, 21, 21>::Identity();

public:
  bool state_transition_jacobians = true;

  // Alpha and beta Jacobians wrt linearization orientation
  Eigen::Matrix<double, 3, 3> O_a = Eigen::Matrix<double, 3, 3>::Zero();
  Eigen::Matrix<double, 3, 3> O_b = Eigen::Matrix<double, 3, 3>::Zero();

  CpiV2(double sigma_w, double sigma_wb, double sigma_a, double sigma_ab, bool imu_avg_ = false)
      : CpiBase(sigma_w, sigma_wb, sigma_a, sigma_ab, imu_avg_) {}

  virtual ~CpiV2() {}

  void feed_IMU(double t_0, double t_1, Eigen::Matrix<double, 3, 1> w_m_0, Eigen::Matrix<double, 3, 1> a_m_0,
                Eigen::Matrix<double, 3, 1> w_m_1 = Eigen::Matrix<double, 3, 1>::Zero(),
                Eigen::Matrix<double, 3, 1> a_m_1 = Eigen::Matrix<double, 3, 1>::Zero());
};

} // namespace ov_core

#endif /* CPI_V2_H */
