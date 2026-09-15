"""
Calibration pipeline: reads sensor data, processes all measurements,
generates calibration report and diagnostic plot.
"""


import json
import sys
import tomllib
import torch

sys.path.insert(0, "/app")
from rotation_lib import (
    quaternion_to_matrix,
    matrix_to_quaternion,
    axis_angle_to_quaternion,
    euler_angles_to_matrix,
    rotation_6d_to_matrix,
    standardize_quaternion,
)
from rotation_analysis import geodesic_distance, slerp, karcher_mean

# ── Read configuration ──
with open("/app/analysis_config.toml", "rb") as f:
    config = tomllib.load(f)

max_iter = config["karcher_mean"]["max_iterations"]
convergence_tol = config["karcher_mean"]["convergence_tolerance"]
num_steps = config["slerp"]["num_steps"]
report_path = config["output"]["report_path"]
plot_path = config["output"]["diagnostic_plot_path"]

# ── Read sensor data ──
with open("/app/sensor_data.json") as f:
    sensor_data = json.load(f)

# ── Convert all measurements to quaternions ──
sensor_quaternions = {}
for sensor_id, sensor_info in sensor_data["sensors"].items():
    fmt = sensor_info["format"]
    measurements = sensor_info["measurements"]
    quats = []
    for m in measurements:
        t = torch.tensor(m, dtype=torch.float32)
        if fmt == "quaternion":
            q = standardize_quaternion(t.unsqueeze(0))[0]
        elif fmt == "axis_angle":
            q = axis_angle_to_quaternion(t.unsqueeze(0))[0]
        elif fmt == "rotation_matrix":
            R = t.reshape(3, 3).unsqueeze(0)
            q = matrix_to_quaternion(R)[0]
        elif fmt.startswith("euler_"):
            convention = fmt.split("_", 1)[1]
            R = euler_angles_to_matrix(t.unsqueeze(0), convention)
            q = matrix_to_quaternion(R)[0]
        elif fmt == "rotation_6d":
            R = rotation_6d_to_matrix(t.unsqueeze(0))
            q = matrix_to_quaternion(R)[0]
        else:
            raise ValueError(f"Unknown sensor format: {fmt}")
        q = standardize_quaternion(q.unsqueeze(0))[0]
        quats.append(q)
    sensor_quaternions[sensor_id] = torch.stack(quats)

# ── Compute overall Karcher mean ──
all_quats = torch.cat(list(sensor_quaternions.values()), dim=0)
overall_mean_q = karcher_mean(all_quats, max_iter=max_iter, tol=convergence_tol)
overall_mean_R = quaternion_to_matrix(overall_mean_q.unsqueeze(0))[0]
print(f"Overall Karcher mean: {overall_mean_q.tolist()}")

# ── Compute per-sensor statistics ──
per_sensor_stats = {}
sensor_means = {}
for sensor_id, quats in sensor_quaternions.items():
    # Individual Karcher mean for this sensor
    s_mean_q = karcher_mean(quats, max_iter=max_iter, tol=convergence_tol)
    sensor_means[sensor_id] = s_mean_q

    # Geodesic distances from overall mean
    Rs = quaternion_to_matrix(quats)
    R_expanded = overall_mean_R.unsqueeze(0).expand_as(Rs)
    dists = geodesic_distance(Rs, R_expanded)

    per_sensor_stats[sensor_id] = {
        "mean_geodesic_distance": round(dists.mean().item(), 8),
        "max_geodesic_distance": round(dists.max().item(), 8),
        "individual_mean_quaternion": [round(x, 8) for x in s_mean_q.tolist()],
    }
    print(f"  {sensor_id}: mean_dist={dists.mean().item():.6f}, max_dist={dists.max().item():.6f}")

# ── Rank sensors by ascending mean geodesic distance ──
sensor_rankings = sorted(
    per_sensor_stats.keys(),
    key=lambda s: per_sensor_stats[s]["mean_geodesic_distance"],
)
print(f"Sensor rankings (best to worst): {sensor_rankings}")

# ── SLERP trajectory between best and worst sensor means ──
best = sensor_rankings[0]
worst = sensor_rankings[-1]
q_best = sensor_means[best].unsqueeze(0)
q_worst = sensor_means[worst].unsqueeze(0)

slerp_quats = []
for i in range(num_steps):
    t_val = i / (num_steps - 1) if num_steps > 1 else 0.0
    q_interp = slerp(q_best, q_worst, t_val)
    slerp_quats.append([round(x, 8) for x in q_interp[0].tolist()])

# ── Build and write report ──
report = {
    "overall_mean_quaternion": [round(x, 8) for x in overall_mean_q.tolist()],
    "sensor_rankings": sensor_rankings,
    "per_sensor_stats": per_sensor_stats,
    "slerp_trajectory": {
        "from_sensor": best,
        "to_sensor": worst,
        "quaternions": slerp_quats,
    },
}

with open(report_path, "w") as f:
    json.dump(report, f, indent=2)
print(f"Report written to {report_path}")

# ── Generate diagnostic plot ──
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 6))
sensor_ids = sensor_rankings
mean_dists = [per_sensor_stats[s]["mean_geodesic_distance"] for s in sensor_ids]
max_dists = [per_sensor_stats[s]["max_geodesic_distance"] for s in sensor_ids]

x = list(range(len(sensor_ids)))
width = 0.35
ax.bar([i - width / 2 for i in x], mean_dists, width, label="Mean geodesic distance", color="steelblue")
ax.bar([i + width / 2 for i in x], max_dists, width, label="Max geodesic distance", color="coral")
ax.set_xlabel("Sensor (ranked best to worst)")
ax.set_ylabel("Geodesic Distance (radians)")
ax.set_title("Per-Sensor Rotation Measurement Quality")
ax.set_xticks(x)
ax.set_xticklabels(sensor_ids, rotation=15)
ax.legend()
fig.tight_layout()
fig.savefig(plot_path, dpi=100)
print(f"Diagnostic plot saved to {plot_path}")

print("Calibration pipeline complete.")
