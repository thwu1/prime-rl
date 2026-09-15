"""Generate synthetic point cloud registration data in HDF5 format with known ground truth."""
import numpy as np
import h5py
import json
import os


def make_swiss_roll(rng, n_points, scale_y=15.0):
    """Generate a Swiss Roll manifold — highly asymmetric, no rotational symmetry."""
    t = 1.5 * np.pi * (1 + 2 * rng.uniform(0, 1, n_points))
    x = t * np.cos(t)
    y = scale_y * rng.uniform(0, 1, n_points)
    z = t * np.sin(t)
    pts = np.column_stack([x, y, z])
    pts = (pts - pts.mean(axis=0)) / pts.std()
    return pts


def rodrigues(axis, angle_rad):
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + np.sin(angle_rad) * K + (1 - np.cos(angle_rad)) * (K @ K)


def save_h5(path, points, rng):
    """Save point cloud to HDF5 with hierarchical structure and gzip compression."""
    n = len(points)
    with h5py.File(path, "w") as f:
        f.attrs["format_version"] = "1.0"
        f.attrs["num_points"] = n
        f.attrs["coordinate_frame"] = "right_handed"

        grp = f.create_group("pointcloud")
        ds_xyz = grp.create_dataset(
            "xyz", data=points, dtype="float64",
            compression="gzip", compression_opts=4,
        )
        ds_xyz.attrs["units"] = "meters"
        ds_xyz.attrs["description"] = "3D point coordinates"

        ds_rgb = grp.create_dataset(
            "rgb", data=rng.randint(0, 256, (n, 3), dtype=np.uint8),
            compression="gzip", compression_opts=4,
        )
        ds_rgb.attrs["description"] = "Per-point RGB color"

        meta = f.create_group("metadata")
        meta.attrs["sensor"] = "synthetic"
        meta.attrs["noise_model"] = "isotropic_gaussian"


os.makedirs("/app/data", exist_ok=True)

# ---- Problem A: primary registration ----
rng_a = np.random.RandomState(42)
source_a = make_swiss_roll(rng_a, 800)

axis_a = np.array([1.0, 2.0, 3.0])
axis_a /= np.linalg.norm(axis_a)
R_gt_a = rodrigues(axis_a, np.deg2rad(42.0))
t_gt_a = np.array([0.5, -0.3, 0.8])
s_gt_a = 1.12

target_clean_a = s_gt_a * (source_a @ R_gt_a.T) + t_gt_a
target_noisy_a = target_clean_a + rng_a.normal(0, 0.02, target_clean_a.shape)

bbox_min_a = target_noisy_a.min(axis=0) - 0.5
bbox_max_a = target_noisy_a.max(axis=0) + 0.5
outliers_a = rng_a.uniform(bbox_min_a, bbox_max_a, (200, 3))
target_a = np.vstack([target_noisy_a, outliers_a])
target_a = target_a[rng_a.permutation(len(target_a))]

save_h5("/app/data/source.h5", source_a, rng_a)
save_h5("/app/data/target.h5", target_a, rng_a)

with open("/app/data/metadata.json", "w") as f:
    json.dump(
        {
            "description": (
                "Point clouds stored in HDF5 format. Use h5ls / h5dump to inspect "
                "file structure and discover dataset paths."
            ),
            "n_source": int(len(source_a)),
            "n_target": int(len(target_a)),
            "task": (
                "Recover R (3x3 rotation), t (3-vector), s (scalar) such that "
                "target_inliers ~ s * (source @ R.T) + t + noise"
            ),
        },
        f,
        indent=2,
    )

# ---- Problem B: generalization (different shape, different transform) ----
rng_b = np.random.RandomState(137)

n_b = 600
t_b = 3 * np.pi * rng_b.uniform(0, 1, n_b) - 1.5 * np.pi
x_b = np.sin(t_b)
y_b = 10.0 * rng_b.uniform(0, 1, n_b)
z_b = np.sign(t_b) * (np.cos(t_b) - 1)
source_b_raw = np.column_stack([x_b, y_b, z_b])
source_b = (source_b_raw - source_b_raw.mean(axis=0)) / source_b_raw.std()

axis_b = np.array([-1.0, 0.5, 2.0])
axis_b /= np.linalg.norm(axis_b)
R_gt_b = rodrigues(axis_b, np.deg2rad(65.0))
t_gt_b = np.array([-0.4, 0.6, -0.2])
s_gt_b = 0.93

target_clean_b = s_gt_b * (source_b @ R_gt_b.T) + t_gt_b
target_noisy_b = target_clean_b + rng_b.normal(0, 0.025, target_clean_b.shape)

bbox_min_b = target_noisy_b.min(axis=0) - 0.5
bbox_max_b = target_noisy_b.max(axis=0) + 0.5
outliers_b = rng_b.uniform(bbox_min_b, bbox_max_b, (180, 3))
target_b = np.vstack([target_noisy_b, outliers_b])
target_b = target_b[rng_b.permutation(len(target_b))]

save_h5("/app/data/source_b.h5", source_b, rng_b)
save_h5("/app/data/target_b.h5", target_b, rng_b)
