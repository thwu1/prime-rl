
/*
 * MIT License
 * Copyright (c) 2018 Kevin Eckenhoff
 * Copyright (c) 2018 Patrick Geneva
 * Copyright (c) 2018 Guoquan Huang
 */

#include "CpiV2.h"

#include "utils/quat_ops.h"

using namespace ov_core;

void CpiV2::feed_IMU(double t_0, double t_1, Eigen::Matrix<double, 3, 1> w_m_0, Eigen::Matrix<double, 3, 1> a_m_0,
                     Eigen::Matrix<double, 3, 1> w_m_1, Eigen::Matrix<double, 3, 1> a_m_1) {

  // Get time difference
  double delta_t = t_1 - t_0;
  DT += delta_t;

  // If no time has passed do nothing
  if (delta_t == 0) {
    return;
  }

  // Get estimated imu readings
  Eigen::Matrix<double, 3, 1> w_hat = w_m_0 - b_w_lin;
  Eigen::Matrix<double, 3, 1> a_hat = a_m_0 - b_a_lin - R_k2tau * quat_2_Rot(q_k_lin) * grav;

  // If averaging, average
  // Note: we will average the LOCAL acceleration after getting the relative rotation
  if (imu_avg) {
    w_hat += w_m_1 - b_w_lin;
    w_hat = 0.5 * w_hat;
  }

  // Get angle change w*dt
  Eigen::Matrix<double, 3, 1> w_hatdt = w_hat * delta_t;

  // Get entries of w_hat
  double w_1 = w_hat(0, 0);
  double w_2 = w_hat(1, 0);
  double w_3 = w_hat(2, 0);

  // Get magnitude of w and wdt
  double mag_w = w_hat.norm();
  double w_dt = mag_w * delta_t;

  // Threshold to determine if equations will be unstable
  bool small_w = (mag_w < 0.008726646);

  // Get some of the variables used in the preintegration equations
  double dt_2 = pow(delta_t, 2);
  double cos_wt = cos(w_dt);
  double sin_wt = sin(w_dt);

  Eigen::Matrix<double, 3, 3> w_x = skew_x(w_hat);
  Eigen::Matrix<double, 3, 3> w_tx = skew_x(w_hatdt);
  Eigen::Matrix<double, 3, 3> w_x_2 = w_x * w_x;

  //==========================================================================
  // MEASUREMENT MEANS
  //==========================================================================

  // Get relative rotation
  Eigen::Matrix<double, 3, 3> R_tau2tau1 = small_w ? eye3 - delta_t * w_x + (pow(delta_t, 2) / 2) * w_x_2
                                                   : eye3 - (sin_wt / mag_w) * w_x + ((1.0 - cos_wt) / (pow(mag_w, 2.0))) * w_x_2;

  // Updated roation and its transpose
  Eigen::Matrix<double, 3, 3> R_k2tau1 = R_tau2tau1 * R_k2tau;
  Eigen::Matrix<double, 3, 3> R_tau12k = R_k2tau1.transpose();

  // If averaging, average the LOCAL acceleration
  if (imu_avg) {
    a_hat += a_m_1 - b_a_lin - R_k2tau1 * quat_2_Rot(q_k_lin) * grav;
    a_hat = 0.5 * a_hat;
  }
  Eigen::Matrix<double, 3, 3> a_x = skew_x(a_hat);

  // Intermediate variables
  double f_1, f_2, f_3, f_4;

  if (small_w) {
    f_1 = -(pow(delta_t, 3) / 3);
    f_2 = (pow(delta_t, 4) / 8);
    f_3 = -(pow(delta_t, 2) / 2);
    f_4 = (pow(delta_t, 3) / 6);
  } else {
    f_1 = (w_dt * cos_wt - sin_wt) / (pow(mag_w, 3));
    f_2 = (pow(w_dt, 2) - 2 * cos_wt - 2 * w_dt * sin_wt + 2) / (2 * pow(mag_w, 4));
    f_3 = -(1 - cos_wt) / pow(mag_w, 2);
    f_4 = (w_dt - sin_wt) / pow(mag_w, 3);
  }

  Eigen::Matrix<double, 3, 3> alpha_arg = ((dt_2 / 2.0) * eye3 + f_1 * w_x + f_2 * w_x_2);
  Eigen::Matrix<double, 3, 3> Beta_arg = (delta_t * eye3 + f_3 * w_x + f_4 * w_x_2);

  Eigen::Matrix<double, 3, 3> H_al = R_tau12k * alpha_arg;
  Eigen::Matrix<double, 3, 3> H_be = R_tau12k * Beta_arg;

  alpha_tau += beta_tau * delta_t + H_al * a_hat;
  beta_tau += H_be * a_hat;

  //==========================================================================
  // BIAS JACOBIANS (ANALYTICAL)
  //==========================================================================

  Eigen::Matrix<double, 3, 3> J_r_tau1 =
      small_w ? eye3 - .5 * w_tx + (1.0 / 6.0) * w_tx * w_tx
              : eye3 - ((1 - cos_wt) / (pow((w_dt), 2.0))) * w_tx + ((w_dt - sin_wt) / (pow(w_dt, 3.0))) * w_tx * w_tx;

  Eigen::Matrix<double, 3, 3> J_save = J_q;
  J_q = R_tau2tau1 * J_q + J_r_tau1 * delta_t;

  H_a -= H_al;
  H_a += delta_t * H_b;
  H_b -= H_be;

  // Update alpha and beta in respect to q_GtoLIN Jacobian
  Eigen::Matrix<double, 3, 1> g_k = quat_2_Rot(q_k_lin) * grav;
  O_a += delta_t * O_b;
  O_a += -H_al * R_k2tau * skew_x(g_k);
  O_b += -H_be * R_k2tau * skew_x(g_k);

  Eigen::MatrixXd d_R_bw_1 = -R_tau12k * skew_x(J_q * e_1);
  Eigen::MatrixXd d_R_bw_2 = -R_tau12k * skew_x(J_q * e_2);
  Eigen::MatrixXd d_R_bw_3 = -R_tau12k * skew_x(J_q * e_3);

  // df/dbw terms (same as Model 1)
  double df_1_dbw_1, df_1_dbw_2, df_1_dbw_3;
  double df_2_dbw_1, df_2_dbw_2, df_2_dbw_3;
  double df_3_dbw_1, df_3_dbw_2, df_3_dbw_3;
  double df_4_dbw_1, df_4_dbw_2, df_4_dbw_3;

  if (small_w) {
    double df_1_dw_mag = -(pow(delta_t, 5) / 15);
    df_1_dbw_1 = w_1 * df_1_dw_mag; df_1_dbw_2 = w_2 * df_1_dw_mag; df_1_dbw_3 = w_3 * df_1_dw_mag;
    double df_2_dw_mag = (pow(delta_t, 6) / 72);
    df_2_dbw_1 = w_1 * df_2_dw_mag; df_2_dbw_2 = w_2 * df_2_dw_mag; df_2_dbw_3 = w_3 * df_2_dw_mag;
    double df_3_dw_mag = -(pow(delta_t, 4) / 12);
    df_3_dbw_1 = w_1 * df_3_dw_mag; df_3_dbw_2 = w_2 * df_3_dw_mag; df_3_dbw_3 = w_3 * df_3_dw_mag;
    double df_4_dw_mag = (pow(delta_t, 5) / 60);
    df_4_dbw_1 = w_1 * df_4_dw_mag; df_4_dbw_2 = w_2 * df_4_dw_mag; df_4_dbw_3 = w_3 * df_4_dw_mag;
  } else {
    double df_1_dw_mag = (pow(w_dt, 2) * sin_wt - 3 * sin_wt + 3 * w_dt * cos_wt) / pow(mag_w, 5);
    df_1_dbw_1 = w_1 * df_1_dw_mag; df_1_dbw_2 = w_2 * df_1_dw_mag; df_1_dbw_3 = w_3 * df_1_dw_mag;
    double df_2_dw_mag = (pow(w_dt, 2) - 4 * cos_wt - 4 * w_dt * sin_wt + pow(w_dt, 2) * cos_wt + 4) / (pow(mag_w, 6));
    df_2_dbw_1 = w_1 * df_2_dw_mag; df_2_dbw_2 = w_2 * df_2_dw_mag; df_2_dbw_3 = w_3 * df_2_dw_mag;
    double df_3_dw_mag = (2 * (cos_wt - 1) + w_dt * sin_wt) / (pow(mag_w, 4));
    df_3_dbw_1 = w_1 * df_3_dw_mag; df_3_dbw_2 = w_2 * df_3_dw_mag; df_3_dbw_3 = w_3 * df_3_dw_mag;
    double df_4_dw_mag = (2 * w_dt + w_dt * cos_wt - 3 * sin_wt) / (pow(mag_w, 5));
    df_4_dbw_1 = w_1 * df_4_dw_mag; df_4_dbw_2 = w_2 * df_4_dw_mag; df_4_dbw_3 = w_3 * df_4_dw_mag;
  }

  Eigen::Matrix<double, 3, 1> g_tau = R_k2tau * quat_2_Rot(q_k_lin) * grav;

  J_a += J_b * delta_t;
  J_a.block(0, 0, 3, 1) +=
      (d_R_bw_1 * alpha_arg + R_tau12k * (df_1_dbw_1 * w_x - f_1 * e_1x + df_2_dbw_1 * w_x_2 - f_2 * (e_1x * w_x + w_x * e_1x))) * a_hat -
      H_al * skew_x((J_save * e_1)) * g_tau;
  J_a.block(0, 1, 3, 1) +=
      (d_R_bw_2 * alpha_arg + R_tau12k * (df_1_dbw_2 * w_x - f_1 * e_2x + df_2_dbw_2 * w_x_2 - f_2 * (e_2x * w_x + w_x * e_2x))) * a_hat -
      H_al * skew_x((J_save * e_2)) * g_tau;
  J_a.block(0, 2, 3, 1) +=
      (d_R_bw_3 * alpha_arg + R_tau12k * (df_1_dbw_3 * w_x - f_1 * e_3x + df_2_dbw_3 * w_x_2 - f_2 * (e_3x * w_x + w_x * e_3x))) * a_hat -
      H_al * skew_x((J_save * e_3)) * g_tau;
  J_b.block(0, 0, 3, 1) +=
      (d_R_bw_1 * Beta_arg + R_tau12k * (df_3_dbw_1 * w_x - f_3 * e_1x + df_4_dbw_1 * w_x_2 - f_4 * (e_1x * w_x + w_x * e_1x))) * a_hat -
      -H_be * skew_x((J_save * e_1)) * g_tau;
  J_b.block(0, 1, 3, 1) +=
      (d_R_bw_2 * Beta_arg + R_tau12k * (df_3_dbw_2 * w_x - f_3 * e_2x + df_4_dbw_2 * w_x_2 - f_4 * (e_2x * w_x + w_x * e_2x))) * a_hat -
      H_be * skew_x((J_save * e_2)) * g_tau;
  J_b.block(0, 2, 3, 1) +=
      (d_R_bw_3 * Beta_arg + R_tau12k * (df_3_dbw_3 * w_x - f_3 * e_3x + df_4_dbw_3 * w_x_2 - f_4 * (e_3x * w_x + w_x * e_3x))) * a_hat -
      H_be * skew_x((J_save * e_3)) * g_tau;

  //==========================================================================
  // MEASUREMENT COVARIANCE
  //==========================================================================

  Eigen::Matrix<double, 3, 3> R_G_to_k = quat_2_Rot(q_k_lin);
  double dt_mid = delta_t / 2.0;
  Eigen::Matrix<double, 3, 3> R_mid;

  R_mid = small_w ? eye3 - dt_mid * w_x + (pow(dt_mid, 2) / 2) * w_x_2
                  : eye3 - (sin(mag_w * dt_mid) / mag_w) * w_x + ((1.0 - cos(mag_w * dt_mid)) / (pow(mag_w, 2.0))) * w_x_2;
  R_mid = R_mid * R_k2tau;

  // k1
  Eigen::Matrix<double, 21, 21> F_k1 = Eigen::Matrix<double, 21, 21>::Zero();
  F_k1.block(0, 0, 3, 3) = -w_x;
  F_k1.block(0, 3, 3, 3) = -eye3;
  F_k1.block(6, 0, 3, 3) = -R_k2tau.transpose() * a_x;
  F_k1.block(6, 9, 3, 3) = -R_k2tau.transpose();
  F_k1.block(6, 15, 3, 3) = -R_k2tau.transpose() * skew_x(R_k2tau * R_G_to_k * grav);
  F_k1.block(6, 18, 3, 3) = -R_k2tau.transpose() * R_k2tau * skew_x(R_G_to_k * grav);
  F_k1.block(12, 6, 3, 3) = eye3;

  Eigen::Matrix<double, 21, 12> G_k1 = Eigen::Matrix<double, 21, 12>::Zero();
  G_k1.block(0, 0, 3, 3) = -eye3;
  G_k1.block(3, 3, 3, 3) = eye3;
  G_k1.block(6, 6, 3, 3) = -R_k2tau.transpose();
  G_k1.block(9, 9, 3, 3) = eye3;

  Eigen::Matrix<double, 21, 21> Phi_dot_k1 = F_k1;
  Eigen::Matrix<double, 21, 21> P_dot_k1 = F_k1 * P_big + P_big * F_k1.transpose() + G_k1 * Q_c * G_k1.transpose();

  // k2
  Eigen::Matrix<double, 21, 21> F_k2 = Eigen::Matrix<double, 21, 21>::Zero();
  F_k2.block(0, 0, 3, 3) = -w_x;
  F_k2.block(0, 3, 3, 3) = -eye3;
  F_k2.block(6, 0, 3, 3) = -R_mid.transpose() * a_x;
  F_k2.block(6, 9, 3, 3) = -R_mid.transpose();
  F_k2.block(6, 15, 3, 3) = -R_mid.transpose() * skew_x(R_k2tau * R_G_to_k * grav);
  F_k2.block(6, 18, 3, 3) = -R_mid.transpose() * R_k2tau * skew_x(R_G_to_k * grav);
  F_k2.block(12, 6, 3, 3) = eye3;

  Eigen::Matrix<double, 21, 12> G_k2 = Eigen::Matrix<double, 21, 12>::Zero();
  G_k2.block(0, 0, 3, 3) = -eye3;
  G_k2.block(3, 3, 3, 3) = eye3;
  G_k2.block(6, 6, 3, 3) = -R_mid.transpose();
  G_k2.block(9, 9, 3, 3) = eye3;

  Eigen::Matrix<double, 21, 21> Phi_k2 = Eigen::Matrix<double, 21, 21>::Identity() + Phi_dot_k1 * dt_mid;
  Eigen::Matrix<double, 21, 21> P_k2 = P_big + P_dot_k1 * dt_mid;
  Eigen::Matrix<double, 21, 21> Phi_dot_k2 = F_k2 * Phi_k2;
  Eigen::Matrix<double, 21, 21> P_dot_k2 = F_k2 * P_k2 + P_k2 * F_k2.transpose() + G_k2 * Q_c * G_k2.transpose();

  // k3
  Eigen::Matrix<double, 21, 21> F_k3 = F_k2;
  Eigen::Matrix<double, 21, 12> G_k3 = G_k2;

  Eigen::Matrix<double, 21, 21> Phi_k3 = Eigen::Matrix<double, 21, 21>::Identity() + Phi_dot_k2 * dt_mid;
  Eigen::Matrix<double, 21, 21> P_k3 = P_big + P_dot_k2 * dt_mid;
  Eigen::Matrix<double, 21, 21> Phi_dot_k3 = F_k3 * Phi_k3;
  Eigen::Matrix<double, 21, 21> P_dot_k3 = F_k3 * P_k3 + P_k3 * F_k3.transpose() + G_k3 * Q_c * G_k3.transpose();

  // k4
  Eigen::Matrix<double, 21, 21> F_k4 = Eigen::Matrix<double, 21, 21>::Zero();
  F_k4.block(0, 0, 3, 3) = -w_x;
  F_k4.block(0, 3, 3, 3) = -eye3;
  F_k4.block(6, 0, 3, 3) = -R_k2tau1.transpose() * a_x;
  F_k4.block(6, 9, 3, 3) = -R_k2tau1.transpose();
  F_k4.block(6, 15, 3, 3) = -R_k2tau1.transpose() * skew_x(R_k2tau * R_G_to_k * grav);
  F_k4.block(6, 18, 3, 3) = -R_k2tau1.transpose() * R_k2tau * skew_x(R_G_to_k * grav);
  F_k4.block(12, 6, 3, 3) = eye3;

  Eigen::Matrix<double, 21, 12> G_k4 = Eigen::Matrix<double, 21, 12>::Zero();
  G_k4.block(0, 0, 3, 3) = -eye3;
  G_k4.block(3, 3, 3, 3) = eye3;
  G_k4.block(6, 6, 3, 3) = -R_k2tau1.transpose();
  G_k4.block(9, 9, 3, 3) = eye3;

  Eigen::Matrix<double, 21, 21> Phi_k4 = Eigen::Matrix<double, 21, 21>::Identity() + Phi_dot_k3 * delta_t;
  Eigen::Matrix<double, 21, 21> P_k4 = P_big + P_dot_k3 * delta_t;
  Eigen::Matrix<double, 21, 21> Phi_dot_k4 = F_k4 * Phi_k4;
  Eigen::Matrix<double, 21, 21> P_dot_k4 = F_k4 * P_k4 + P_k4 * F_k4.transpose() + G_k4 * Q_c * G_k4.transpose();

  // done
  P_big += (delta_t / 6.0) * (P_dot_k1 + 2.0 * P_dot_k2 + 2.0 * P_dot_k3 + P_dot_k4);
  P_big = 0.5 * (P_big + P_big.transpose());

  Eigen::Matrix<double, 21, 21> Phi =
      Eigen::Matrix<double, 21, 21>::Identity() + (delta_t / 6.0) * (Phi_dot_k1 + 2.0 * Phi_dot_k2 + 2.0 * Phi_dot_k3 + Phi_dot_k4);

  //==========================================================================
  // CLONE TO NEW SAMPLE TIME AND MARGINALIZE OLD SAMPLE TIME
  //==========================================================================

  Eigen::Matrix<double, 21, 21> B_k = Eigen::Matrix<double, 21, 21>::Identity();
  B_k.block(15, 15, 3, 3).setZero();
  B_k.block(15, 0, 3, 3) = Eigen::Matrix<double, 3, 3>::Identity();

  P_big = B_k * P_big * B_k.transpose();
  P_big = 0.5 * (P_big + P_big.transpose());
  Discrete_J_b = B_k * Phi * Discrete_J_b;

  P_meas = P_big.block(0, 0, 15, 15);

  if (state_transition_jacobians) {
    J_q = -Discrete_J_b.block(0, 3, 3, 3);
    J_a = Discrete_J_b.block(12, 3, 3, 3);
    J_b = Discrete_J_b.block(6, 3, 3, 3);
    H_a = Discrete_J_b.block(12, 9, 3, 3);
    H_b = Discrete_J_b.block(6, 9, 3, 3);
    O_a = Discrete_J_b.block(12, 18, 3, 3);
    O_b = Discrete_J_b.block(6, 18, 3, 3);
  }

  R_k2tau = R_k2tau1;
  q_k2tau = rot_2_quat(R_k2tau);
}
