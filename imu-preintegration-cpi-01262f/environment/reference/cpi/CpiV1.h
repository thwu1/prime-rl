#ifndef CPI_V1_H
#define CPI_V1_H

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
 * @brief Model 1 of continuous preintegration.
 *
 * This model is the "piecewise constant measurement assumption" which was first presented in:
 * > Eckenhoff, Kevin, Patrick Geneva, and Guoquan Huang.
 * > "High-accuracy preintegration for visual inertial navigation."
 * > International Workshop on the Algorithmic Foundations of Robotics. 2016.
 * Please see the following publication for details on the theory @cite Eckenhoff2019IJRR :
 * > Continuous Preintegration Theory for Graph-based Visual-Inertial Navigation
 * > Authors: Kevin Eckenhoff, Patrick Geneva, and Guoquan Huang
 * > http://udel.edu/~ghuang/papers/tr_cpi.pdf
 */
class CpiV1 : public CpiBase {

public:
  CpiV1(double sigma_w, double sigma_wb, double sigma_a, double sigma_ab, bool imu_avg_ = false)
      : CpiBase(sigma_w, sigma_wb, sigma_a, sigma_ab, imu_avg_) {}

  virtual ~CpiV1() {}

  void feed_IMU(double t_0, double t_1, Eigen::Matrix<double, 3, 1> w_m_0, Eigen::Matrix<double, 3, 1> a_m_0,
                Eigen::Matrix<double, 3, 1> w_m_1 = Eigen::Matrix<double, 3, 1>::Zero(),
                Eigen::Matrix<double, 3, 1> a_m_1 = Eigen::Matrix<double, 3, 1>::Zero());
};

} // namespace ov_core

#endif /* CPI_V1_H */
