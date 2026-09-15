"""System identification for quadrotor dynamics.

Estimate unknown physical parameters from recorded flight data.

Training data NPZ files contain:
  - times: (T+1,) timestamps [s]
  - positions: (T+1, 3) measured positions (with noise) [m]
  - quaternions: (T+1, 4) measured orientations [qx, qy, qz, qw]
  - velocities: (T+1, 3) measured velocities (with noise) [m/s]
  - angular_velocities: (T+1, 3) measured angular velocities (with noise) [rad/s]
  - rotor_rpms: (T, 4) motor commands (exact) [RPM]

States have T+1 entries; rotor_rpms has T entries.
"""

import numpy as np


def estimate_parameters(data_files, known_params):
    """Estimate unknown physics parameters from flight recordings.

    Args:
        data_files: list of str, paths to training .npz files
        known_params: dict with keys: arm_length, J (3x3), J_inv (3x3),
                      drag (3x3), g

    Returns:
        dict with keys: mass (float), k_f (float), k_m (float)
    """
    raise NotImplementedError("Implement estimate_parameters")
