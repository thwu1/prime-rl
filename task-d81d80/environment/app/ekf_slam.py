"""EKF-SLAM for 2D robot with range-bearing landmark observations.

State vector: [x, y, theta, m1_x, m1_y, m2_x, m2_y, ..., mN_x, mN_y]
Control input: [v, omega] (linear velocity, angular velocity)
Observation: [range, bearing] for each detected landmark

The motion model is implemented in C (libmotion.so) and called via ctypes.
The observation model and filter update logic are in Python.

"""

import ctypes
import os
import numpy as np


def normalize_angle(angle):
    """Wrap angle to [-pi, pi]."""
    return (angle + np.pi) % (2 * np.pi) - np.pi


class EKFSLAM:
    def __init__(self, sigma_v, sigma_omega, sigma_range, sigma_bearing,
                 n_landmarks):
        self.sigma_v = sigma_v
        self.sigma_omega = sigma_omega
        self.n_landmarks = n_landmarks

        self.state_dim = 3 + 2 * n_landmarks
        self.mu = np.zeros(self.state_dim)
        self.Sigma = np.zeros((self.state_dim, self.state_dim))

        # Large initial uncertainty for unobserved landmarks
        for i in range(n_landmarks):
            idx = 3 + 2 * i
            self.Sigma[idx, idx] = 1e6
            self.Sigma[idx + 1, idx + 1] = 1e6

        self.landmark_observed = np.zeros(n_landmarks, dtype=bool)
        self.Qt = np.diag([sigma_range**2, sigma_bearing**2])

        # Load C shared library for motion model
        lib_dir = os.path.dirname(os.path.abspath(__file__))
        lib_path = os.path.join(lib_dir, 'libmotion.so')
        self._motion_lib = ctypes.CDLL(lib_path)

        # Configure C function signatures
        dbl_ptr = ctypes.POINTER(ctypes.c_double)
        dbl = ctypes.c_double

        self._motion_lib.motion_update.restype = None
        self._motion_lib.motion_update.argtypes = [dbl_ptr, dbl, dbl, dbl]

        self._motion_lib.motion_jacobian.restype = None
        self._motion_lib.motion_jacobian.argtypes = [dbl_ptr, dbl, dbl, dbl]

        self._motion_lib.noise_jacobian.restype = None
        self._motion_lib.noise_jacobian.argtypes = [dbl_ptr, dbl, dbl, dbl]

    def predict(self, u, dt):
        """Prediction step: propagate state and covariance via C motion model."""
        v, omega = float(u[0]), float(u[1])
        dt_f = float(dt)
        theta = float(self.mu[2])

        # State update via C library
        state_buf = (ctypes.c_double * 3)(
            float(self.mu[0]), float(self.mu[1]), float(self.mu[2])
        )
        self._motion_lib.motion_update(state_buf, v, omega, dt_f)
        self.mu[0] = state_buf[0]
        self.mu[1] = state_buf[1]
        self.mu[2] = state_buf[2]

        # State Jacobian via C library (3x3, row-major)
        jac_buf = (ctypes.c_double * 9)()
        self._motion_lib.motion_jacobian(jac_buf, v, dt_f, theta)
        Fx_robot = np.array(list(jac_buf)).reshape(3, 3)

        Fx = np.eye(self.state_dim)
        Fx[:3, :3] = Fx_robot

        # Noise Jacobian via C library (3x2, row-major)
        vt_buf = (ctypes.c_double * 6)()
        self._motion_lib.noise_jacobian(vt_buf, v, dt_f, theta)
        Vt = np.array(list(vt_buf)).reshape(3, 2)

        # Map control noise covariance to state space
        Mt = np.diag([self.sigma_v**2, self.sigma_omega**2])
        Rt = Vt @ Mt @ Vt.T

        # Propagate covariance through motion model
        self.Sigma = Fx @ self.Sigma @ Fx.T
        self.Sigma[:3, :3] += Rt

    def update(self, observations):
        """Correction step for all current observations."""
        for landmark_id, z_range, z_bearing in observations:
            if not self.landmark_observed[landmark_id]:
                self._initialize_landmark(landmark_id, z_range, z_bearing)
                continue

            j = landmark_id
            lx = self.mu[3 + 2 * j]
            ly = self.mu[3 + 2 * j + 1]
            rx, ry, rtheta = self.mu[0], self.mu[1], self.mu[2]

            # Predicted observation from current state
            dx = lx - rx
            dy = ly - ry
            q = dx**2 + dy**2
            sqrt_q = np.sqrt(q)

            z_hat = np.array([
                sqrt_q,
                normalize_angle(np.arctan2(dx, dy) - rtheta)
            ])

            # Observation Jacobian (2 x state_dim)
            H = np.zeros((2, self.state_dim))

            # Partials w.r.t. robot pose [x, y, theta]
            H[0, 0] = -dx / sqrt_q
            H[0, 1] = -dy / sqrt_q
            H[0, 2] = 0
            H[1, 0] = dy / q
            H[1, 1] = -dx / q
            H[1, 2] = -1

            # Partials w.r.t. landmark position [lx, ly]
            lidx = 3 + 2 * j
            H[0, lidx] = dx / sqrt_q
            H[0, lidx + 1] = dy / sqrt_q
            H[1, lidx] = -dy / q
            H[1, lidx + 1] = dx / q

            # Innovation (measurement residual)
            innovation = np.array([
                z_range - z_hat[0],
                normalize_angle(z_bearing - z_hat[1])
            ])

            # Innovation covariance and Kalman gain
            S = H @ self.Sigma @ H.T + self.Qt
            K = self.Sigma @ H.T @ np.linalg.inv(S)

            # State and covariance update
            self.mu += K @ innovation
            self.mu[2] = normalize_angle(self.mu[2])
            self.Sigma = (np.eye(self.state_dim) - K @ H) @ self.Sigma

    def _initialize_landmark(self, landmark_id, z_range, z_bearing):
        """Initialize a newly observed landmark in the state vector."""
        rx, ry, rtheta = self.mu[0], self.mu[1], self.mu[2]

        # Convert observation from robot-relative to global frame
        angle = z_bearing

        self.mu[3 + 2 * landmark_id] = rx + z_range * np.cos(angle)
        self.mu[3 + 2 * landmark_id + 1] = ry + z_range * np.sin(angle)

        self.landmark_observed[landmark_id] = True

        # Jacobian of landmark position w.r.t. robot pose
        Gz = np.array([
            [1, 0, -z_range * np.sin(angle)],
            [0, 1,  z_range * np.cos(angle)]
        ])

        # Jacobian of landmark position w.r.t. observation [range, bearing]
        Gr = np.array([
            [np.cos(angle), -z_range * np.sin(angle)],
            [np.sin(angle),  z_range * np.cos(angle)]
        ])

        # Covariance of new landmark
        idx = 3 + 2 * landmark_id
        P_robot = self.Sigma[:3, :3].copy()

        self.Sigma[idx:idx + 2, idx:idx + 2] = (
            Gz @ P_robot @ Gz.T + Gr @ self.Qt @ Gr.T
        )

        # Cross-covariance with robot state
        self.Sigma[idx:idx + 2, :3] = Gz @ P_robot
        self.Sigma[:3, idx:idx + 2] = P_robot @ Gz.T

        # Cross-covariance with previously observed landmarks
        for k in range(self.n_landmarks):
            if k != landmark_id and self.landmark_observed[k]:
                kidx = 3 + 2 * k
                self.Sigma[idx:idx + 2, kidx:kidx + 2] = (
                    Gz @ self.Sigma[:3, kidx:kidx + 2]
                )
                self.Sigma[kidx:kidx + 2, idx:idx + 2] = (
                    self.Sigma[kidx:kidx + 2, :3] @ Gz.T
                )
