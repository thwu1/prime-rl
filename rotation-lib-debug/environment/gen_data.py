"""Generate deterministic sensor calibration data for the rotation task."""


import torch
import json
import math

torch.manual_seed(2024)


def aa_to_quat(aa):
    """Axis-angle to quaternion (w,x,y,z), real-part-first, standardized."""
    theta = torch.norm(aa, dim=-1, keepdim=True)
    safe_theta = torch.where(theta > 1e-12, theta, torch.ones_like(theta))
    half_theta = theta / 2.0
    w = torch.cos(half_theta)
    n = aa / safe_theta
    xyz = n * torch.sin(half_theta)
    q = torch.cat([w, xyz], dim=-1)
    q = torch.where(q[..., 0:1] < 0, -q, q)
    return q


def aa_to_rotmat(aa):
    """Axis-angle to rotation matrix via quaternion formula."""
    q = aa_to_quat(aa)
    r, i, j, k = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    two_s = 2.0 / (q * q).sum(-1)
    mat = torch.stack([
        1 - two_s * (j * j + k * k), two_s * (i * j - k * r), two_s * (i * k + j * r),
        two_s * (i * j + k * r), 1 - two_s * (i * i + k * k), two_s * (j * k - i * r),
        two_s * (i * k - j * r), two_s * (j * k + i * r), 1 - two_s * (i * i + j * j),
    ], dim=-1).reshape(aa.shape[:-1] + (3, 3))
    return mat


def rotmat_to_euler_xyz(R):
    """Rotation matrix to intrinsic XYZ Euler angles."""
    beta = torch.asin(torch.clamp(R[..., 0, 2], -1.0, 1.0))
    alpha = torch.atan2(-R[..., 1, 2], R[..., 2, 2])
    gamma = torch.atan2(-R[..., 0, 1], R[..., 0, 0])
    return torch.stack([alpha, beta, gamma], dim=-1)


# Ground truth rotation: 60 degrees around normalized [1, 2, -1]
axis_raw = torch.tensor([1.0, 2.0, -1.0], dtype=torch.float64)
axis = axis_raw / axis_raw.norm()
angle = math.pi / 3  # 60 degrees
gt_aa = axis * angle

sensors = {}

# Sensor alpha: quaternion format, low noise (sigma=0.02)
noise = torch.randn(15, 3, dtype=torch.float64) * 0.02
noisy_aa = gt_aa.unsqueeze(0) + noise
q = aa_to_quat(noisy_aa)
sensors["sensor_alpha"] = {"format": "quaternion", "measurements": q.tolist()}

# Sensor beta: axis_angle format, high noise (sigma=0.05)
noise = torch.randn(15, 3, dtype=torch.float64) * 0.05
noisy_aa = gt_aa.unsqueeze(0) + noise
sensors["sensor_beta"] = {"format": "axis_angle", "measurements": noisy_aa.tolist()}

# Sensor gamma: rotation_matrix format (3x3), very low noise (sigma=0.01)
noise = torch.randn(15, 3, dtype=torch.float64) * 0.01
noisy_aa = gt_aa.unsqueeze(0) + noise
R = aa_to_rotmat(noisy_aa)
sensors["sensor_gamma"] = {"format": "rotation_matrix", "measurements": R.tolist()}

# Sensor delta: quaternion format, very high noise (sigma=0.08)
noise = torch.randn(15, 3, dtype=torch.float64) * 0.08
noisy_aa = gt_aa.unsqueeze(0) + noise
q = aa_to_quat(noisy_aa)
sensors["sensor_delta"] = {"format": "quaternion", "measurements": q.tolist()}

# Sensor epsilon: euler_XYZ format, medium noise (sigma=0.03) + systematic bias
bias = torch.tensor([0.0, 0.0, 0.15], dtype=torch.float64)
noise = torch.randn(15, 3, dtype=torch.float64) * 0.03
noisy_aa = gt_aa.unsqueeze(0) + noise + bias
R = aa_to_rotmat(noisy_aa)
euler = rotmat_to_euler_xyz(R)
sensors["sensor_epsilon"] = {"format": "euler_XYZ", "measurements": euler.tolist()}

with open("/app/sensor_data.json", "w") as f:
    json.dump({"sensors": sensors}, f, indent=2)

print("Generated /app/sensor_data.json with 5 sensors, 15 measurements each")
