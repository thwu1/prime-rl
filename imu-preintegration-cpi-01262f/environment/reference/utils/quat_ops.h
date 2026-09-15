/*
 * OpenVINS: An Open Platform for Visual-Inertial Research
 * Copyright (C) 2018-2023 Patrick Geneva
 * Copyright (C) 2018-2023 Guoquan Huang
 * Copyright (C) 2018-2023 OpenVINS Contributors
 * Copyright (C) 2018-2019 Kevin Eckenhoff
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

#ifndef OV_CORE_QUAT_OPS_H
#define OV_CORE_QUAT_OPS_H

/*
 * @section Summary
 * This file contains the common utility functions for operating on JPL quaternions.
 * We need to take special care to handle edge cases when converting to and from other rotation formats.
 * All equations are based on the following tech report @cite Trawny2005TR :
 *
 * > Trawny, Nikolas, and Stergios I. Roumeliotis. "Indirect Kalman filter for 3D attitude estimation."
 * > University of Minnesota, Dept. of Comp. Sci. & Eng., Tech. Rep 2 (2005): 2005.
 * > http://mars.cs.umn.edu/tr/reports/Trawny05b.pdf
 *
 * @section JPL Quaternion Definition
 *
 * We define the quaternion as the following linear combination:
 * @f[
 *  \bar{q} = q_4+q_1\mathbf{i}+q_2\mathbf{j}+q_3\mathbf{k}
 * @f]
 * Where i,j,k are defined as the following:
 * @f[
 *  \mathbf{i}^2=-1~,~\mathbf{j}^2=-1~,~\mathbf{k}^2=-1
 * @f]
 * @f[
 *  -\mathbf{i}\mathbf{j}=\mathbf{j}\mathbf{i}=\mathbf{k}
 *  ~,~
 *  -\mathbf{j}\mathbf{k}=\mathbf{k}\mathbf{j}=\mathbf{i}
 *  ~,~
 *  -\mathbf{k}\mathbf{i}=\mathbf{i}\mathbf{k}=\mathbf{j}
 * @f]
 * As noted in @cite Trawny2005TR this does not correspond to the Hamilton notation.
 * The q_4 quantity is the "scalar" portion of the quaternion, while q_1,q_2,q_3 are
 * part of the "vector" portion:
 * @f[
 *  \bar{q} = \begin{bmatrix}q_1\\q_2\\q_3\\q_4\end{bmatrix} = \begin{bmatrix}\mathbf{q}\\q_4\end{bmatrix}
 * @f]
 */

#include <Eigen/Eigen>

namespace ov_core {

/**
 * @brief Returns a JPL quaternion from a rotation matrix
 *
 * Based on equation 74 in Trawny2005TR.
 * Uses the largest diagonal element to avoid division by near-zero.
 */
inline Eigen::Matrix<double, 4, 1> rot_2_quat(const Eigen::Matrix<double, 3, 3> &rot) {
  Eigen::Matrix<double, 4, 1> q;
  double T = rot.trace();
  if ((rot(0, 0) >= T) && (rot(0, 0) >= rot(1, 1)) && (rot(0, 0) >= rot(2, 2))) {
    q(0) = sqrt((1 + (2 * rot(0, 0)) - T) / 4);
    q(1) = (1 / (4 * q(0))) * (rot(0, 1) + rot(1, 0));
    q(2) = (1 / (4 * q(0))) * (rot(0, 2) + rot(2, 0));
    q(3) = (1 / (4 * q(0))) * (rot(1, 2) - rot(2, 1));
  } else if ((rot(1, 1) >= T) && (rot(1, 1) >= rot(0, 0)) && (rot(1, 1) >= rot(2, 2))) {
    q(1) = sqrt((1 + (2 * rot(1, 1)) - T) / 4);
    q(0) = (1 / (4 * q(1))) * (rot(0, 1) + rot(1, 0));
    q(2) = (1 / (4 * q(1))) * (rot(1, 2) + rot(2, 1));
    q(3) = (1 / (4 * q(1))) * (rot(2, 0) - rot(0, 2));
  } else if ((rot(2, 2) >= T) && (rot(2, 2) >= rot(0, 0)) && (rot(2, 2) >= rot(1, 1))) {
    q(2) = sqrt((1 + (2 * rot(2, 2)) - T) / 4);
    q(0) = (1 / (4 * q(2))) * (rot(0, 2) + rot(2, 0));
    q(1) = (1 / (4 * q(2))) * (rot(1, 2) + rot(2, 1));
    q(3) = (1 / (4 * q(2))) * (rot(0, 1) - rot(1, 0));
  } else {
    q(3) = sqrt((1 + T) / 4);
    q(0) = (1 / (4 * q(3))) * (rot(1, 2) - rot(2, 1));
    q(1) = (1 / (4 * q(3))) * (rot(2, 0) - rot(0, 2));
    q(2) = (1 / (4 * q(3))) * (rot(0, 1) - rot(1, 0));
  }
  if (q(3) < 0) {
    q = -q;
  }
  q = q / (q.norm());
  return q;
}

/**
 * @brief Skew-symmetric matrix from a given 3x1 vector
 *
 * Based on equation 6 in Trawny2005TR:
 * \f{align*}{
 *  \lfloor\mathbf{v}\times\rfloor =
 *  \begin{bmatrix}
 *  0 & -v_3 & v_2 \\ v_3 & 0 & -v_1 \\ -v_2 & v_1 & 0
 *  \end{bmatrix}
 * @f}
 */
inline Eigen::Matrix<double, 3, 3> skew_x(const Eigen::Matrix<double, 3, 1> &w) {
  Eigen::Matrix<double, 3, 3> w_x;
  w_x << 0, -w(2), w(1), w(2), 0, -w(0), -w(1), w(0), 0;
  return w_x;
}

/**
 * @brief Converts JPL quaterion to SO(3) rotation matrix
 *
 * Based on equation 62 in Trawny2005TR:
 * \f{align*}{
 *  \mathbf{R} = (2q_4^2-1)\mathbf{I}_3-2q_4\lfloor\mathbf{q}\times\rfloor+2\mathbf{q}\mathbf{q}^\top
 * @f}
 */
inline Eigen::Matrix<double, 3, 3> quat_2_Rot(const Eigen::Matrix<double, 4, 1> &q) {
  Eigen::Matrix<double, 3, 3> q_x = skew_x(q.block(0, 0, 3, 1));
  Eigen::MatrixXd Rot = (2 * std::pow(q(3, 0), 2) - 1) * Eigen::MatrixXd::Identity(3, 3) - 2 * q(3, 0) * q_x +
                        2 * q.block(0, 0, 3, 1) * (q.block(0, 0, 3, 1).transpose());
  return Rot;
}

/**
 * @brief Multiply two JPL quaternions
 *
 * Based on equation 9 in Trawny2005TR.
 * We also enforce that the quaternion is unique by having q_4 be greater than zero.
 * \f{align*}{
 *  \bar{q}\otimes\bar{p}=
 *  \mathcal{L}(\bar{q})\bar{p}=
 *  \begin{bmatrix}
 *  q_4\mathbf{I}_3+\lfloor\mathbf{q}\times\rfloor & \mathbf{q} \\
 *  -\mathbf{q}^\top & q_4
 *  \end{bmatrix}
 *  \begin{bmatrix}
 *  \mathbf{p} \\ p_4
 *  \end{bmatrix}
 * @f}
 */
inline Eigen::Matrix<double, 4, 1> quat_multiply(const Eigen::Matrix<double, 4, 1> &q, const Eigen::Matrix<double, 4, 1> &p) {
  Eigen::Matrix<double, 4, 1> q_t;
  Eigen::Matrix<double, 4, 4> Qm;
  Qm.block(0, 0, 3, 3) = q(3, 0) * Eigen::MatrixXd::Identity(3, 3) - skew_x(q.block(0, 0, 3, 1));
  Qm.block(0, 3, 3, 1) = q.block(0, 0, 3, 1);
  Qm.block(3, 0, 1, 3) = -q.block(0, 0, 3, 1).transpose();
  Qm(3, 3) = q(3, 0);
  q_t = Qm * p;
  if (q_t(3, 0) < 0) {
    q_t *= -1;
  }
  return q_t / q_t.norm();
}

/// @brief Returns vector portion of skew-symmetric
inline Eigen::Matrix<double, 3, 1> vee(const Eigen::Matrix<double, 3, 3> &w_x) {
  Eigen::Matrix<double, 3, 1> w;
  w << w_x(2, 1), w_x(0, 2), w_x(1, 0);
  return w;
}

/**
 * @brief SO(3) matrix exponential
 *
 * SO(3) matrix exponential mapping from the vector to SO(3) lie group.
 * This formula ends up being the Rodrigues rotation formula.
 * \f{align*}{
 * \exp(\mathbf{v}) &=
 * \mathbf{I}
 * +\frac{\sin{\theta}}{\theta}\lfloor\mathbf{v}\times\rfloor
 * +\frac{1-\cos{\theta}}{\theta^2}\lfloor\mathbf{v}\times\rfloor^2
 * \f}
 */
inline Eigen::Matrix<double, 3, 3> exp_so3(const Eigen::Matrix<double, 3, 1> &w) {
  Eigen::Matrix<double, 3, 3> w_x = skew_x(w);
  double theta = w.norm();
  double A, B;
  if (theta < 1e-7) {
    A = 1;
    B = 0.5;
  } else {
    A = sin(theta) / theta;
    B = (1 - cos(theta)) / (theta * theta);
  }
  Eigen::Matrix<double, 3, 3> R;
  if (theta == 0) {
    R = Eigen::MatrixXd::Identity(3, 3);
  } else {
    R = Eigen::MatrixXd::Identity(3, 3) + A * w_x + B * w_x * w_x;
  }
  return R;
}

/**
 * @brief SO(3) matrix logarithm
 *
 * Based on GTSAM implementation for numerical stability.
 */
inline Eigen::Matrix<double, 3, 1> log_so3(const Eigen::Matrix<double, 3, 3> &R) {

  double R11 = R(0, 0), R12 = R(0, 1), R13 = R(0, 2);
  double R21 = R(1, 0), R22 = R(1, 1), R23 = R(1, 2);
  double R31 = R(2, 0), R32 = R(2, 1), R33 = R(2, 2);

  const double tr = R.trace();
  Eigen::Vector3d omega;

  // when trace == -1, i.e., when theta = +-pi, +-3pi, +-5pi, etc.
  if (tr + 1.0 < 1e-10) {
    if (std::abs(R33 + 1.0) > 1e-5)
      omega = (M_PI / sqrt(2.0 + 2.0 * R33)) * Eigen::Vector3d(R13, R23, 1.0 + R33);
    else if (std::abs(R22 + 1.0) > 1e-5)
      omega = (M_PI / sqrt(2.0 + 2.0 * R22)) * Eigen::Vector3d(R12, 1.0 + R22, R32);
    else
      omega = (M_PI / sqrt(2.0 + 2.0 * R11)) * Eigen::Vector3d(1.0 + R11, R21, R31);
  } else {
    double magnitude;
    const double tr_3 = tr - 3.0;
    if (tr_3 < -1e-7) {
      double theta = acos((tr - 1.0) / 2.0);
      magnitude = theta / (2.0 * sin(theta));
    } else {
      magnitude = 0.5 - tr_3 / 12.0;
    }
    omega = magnitude * Eigen::Vector3d(R32 - R23, R13 - R31, R21 - R12);
  }

  return omega;
}

/// @brief SE(3) matrix exponential function
inline Eigen::Matrix4d exp_se3(Eigen::Matrix<double, 6, 1> vec) {
  Eigen::Vector3d w = vec.head(3);
  Eigen::Vector3d u = vec.tail(3);
  double theta = sqrt(w.dot(w));
  Eigen::Matrix3d wskew;
  wskew << 0, -w(2), w(1), w(2), 0, -w(0), -w(1), w(0), 0;
  double A, B, C;
  if (theta < 1e-7) {
    A = 1; B = 0.5; C = 1.0 / 6.0;
  } else {
    A = sin(theta) / theta;
    B = (1 - cos(theta)) / (theta * theta);
    C = (1 - A) / (theta * theta);
  }
  Eigen::Matrix3d I_33 = Eigen::Matrix3d::Identity();
  Eigen::Matrix3d V = I_33 + B * wskew + C * wskew * wskew;
  Eigen::Matrix4d mat = Eigen::Matrix4d::Zero();
  mat.block(0, 0, 3, 3) = I_33 + A * wskew + B * wskew * wskew;
  mat.block(0, 3, 3, 1) = V * u;
  mat(3, 3) = 1;
  return mat;
}

/// @brief SE(3) matrix logarithm
inline Eigen::Matrix<double, 6, 1> log_se3(Eigen::Matrix4d mat) {
  Eigen::Vector3d w = log_so3(mat.block<3, 3>(0, 0));
  Eigen::Vector3d T = mat.block<3, 1>(0, 3);
  const double t = w.norm();
  if (t < 1e-10) {
    Eigen::Matrix<double, 6, 1> log;
    log << w, T;
    return log;
  } else {
    Eigen::Matrix3d W = skew_x(w / t);
    double Tan = tan(0.5 * t);
    Eigen::Vector3d WT = W * T;
    Eigen::Vector3d u = T - (0.5 * t) * WT + (1 - t / (2. * Tan)) * (W * WT);
    Eigen::Matrix<double, 6, 1> log;
    log << w, u;
    return log;
  }
}

/// @brief Hat operator for R^6 -> Lie Algebra se(3)
inline Eigen::Matrix4d hat_se3(const Eigen::Matrix<double, 6, 1> &vec) {
  Eigen::Matrix4d mat = Eigen::Matrix4d::Zero();
  mat.block(0, 0, 3, 3) = skew_x(vec.head(3));
  mat.block(0, 3, 3, 1) = vec.tail(3);
  return mat;
}

/// @brief SE(3) matrix analytical inverse
inline Eigen::Matrix4d Inv_se3(const Eigen::Matrix4d &T) {
  Eigen::Matrix4d Tinv = Eigen::Matrix4d::Identity();
  Tinv.block(0, 0, 3, 3) = T.block(0, 0, 3, 3).transpose();
  Tinv.block(0, 3, 3, 1) = -Tinv.block(0, 0, 3, 3) * T.block(0, 3, 3, 1);
  return Tinv;
}

/// @brief JPL Quaternion inverse
inline Eigen::Matrix<double, 4, 1> Inv(Eigen::Matrix<double, 4, 1> q) {
  Eigen::Matrix<double, 4, 1> qinv;
  qinv.block(0, 0, 3, 1) = -q.block(0, 0, 3, 1);
  qinv(3, 0) = q(3, 0);
  return qinv;
}

/// @brief Integrated quaternion from angular velocity (Omega matrix)
inline Eigen::Matrix<double, 4, 4> Omega(Eigen::Matrix<double, 3, 1> w) {
  Eigen::Matrix<double, 4, 4> mat;
  mat.block(0, 0, 3, 3) = -skew_x(w);
  mat.block(3, 0, 1, 3) = -w.transpose();
  mat.block(0, 3, 3, 1) = w;
  mat(3, 3) = 0;
  return mat;
}

/// @brief Normalizes a quaternion to make sure it is unit norm
inline Eigen::Matrix<double, 4, 1> quatnorm(Eigen::Matrix<double, 4, 1> q_t) {
  if (q_t(3, 0) < 0) {
    q_t *= -1;
  }
  return q_t / q_t.norm();
}

/**
 * @brief Computes left Jacobian of SO(3)
 *
 * \f{align*}{
 * J_l(\boldsymbol\theta) = \frac{\sin\theta}{\theta}\mathbf I +
 * \Big(1-\frac{\sin\theta}{\theta}\Big)\mathbf a \mathbf a^\top +
 * \frac{1-\cos\theta}{\theta}\lfloor \mathbf a \times\rfloor
 * \f}
 */
inline Eigen::Matrix<double, 3, 3> Jl_so3(const Eigen::Matrix<double, 3, 1> &w) {
  double theta = w.norm();
  if (theta < 1e-6) {
    return Eigen::MatrixXd::Identity(3, 3);
  } else {
    Eigen::Matrix<double, 3, 1> a = w / theta;
    Eigen::Matrix<double, 3, 3> J = sin(theta) / theta * Eigen::MatrixXd::Identity(3, 3) +
                                    (1 - sin(theta) / theta) * a * a.transpose() +
                                    ((1 - cos(theta)) / theta) * skew_x(a);
    return J;
  }
}

/// @brief Computes right Jacobian of SO(3). Related to left by Jl(-w) = Jr(w).
inline Eigen::Matrix<double, 3, 3> Jr_so3(const Eigen::Matrix<double, 3, 1> &w) { return Jl_so3(-w); }

/// @brief Gets roll, pitch, yaw of argument rotation (in that order).
inline Eigen::Matrix<double, 3, 1> rot2rpy(const Eigen::Matrix<double, 3, 3> &rot) {
  Eigen::Matrix<double, 3, 1> rpy;
  rpy(1, 0) = atan2(-rot(2, 0), sqrt(rot(0, 0) * rot(0, 0) + rot(1, 0) * rot(1, 0)));
  if (std::abs(cos(rpy(1, 0))) > 1.0e-12) {
    rpy(2, 0) = atan2(rot(1, 0) / cos(rpy(1, 0)), rot(0, 0) / cos(rpy(1, 0)));
    rpy(0, 0) = atan2(rot(2, 1) / cos(rpy(1, 0)), rot(2, 2) / cos(rpy(1, 0)));
  } else {
    rpy(2, 0) = 0;
    rpy(0, 0) = atan2(rot(0, 1), rot(1, 1));
  }
  return rpy;
}

inline Eigen::Matrix<double, 3, 3> rot_x(double t) {
  Eigen::Matrix<double, 3, 3> r;
  double ct = cos(t); double st = sin(t);
  r << 1.0, 0.0, 0.0, 0.0, ct, -st, 0.0, st, ct;
  return r;
}

inline Eigen::Matrix<double, 3, 3> rot_y(double t) {
  Eigen::Matrix<double, 3, 3> r;
  double ct = cos(t); double st = sin(t);
  r << ct, 0.0, st, 0.0, 1.0, 0.0, -st, 0.0, ct;
  return r;
}

inline Eigen::Matrix<double, 3, 3> rot_z(double t) {
  Eigen::Matrix<double, 3, 3> r;
  double ct = cos(t); double st = sin(t);
  r << ct, -st, 0.0, st, ct, 0.0, 0.0, 0.0, 1.0;
  return r;
}

} // namespace ov_core

#endif /* OV_CORE_QUAT_OPS_H */
