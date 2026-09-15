"""Generate synthetic test data and metadata database for the registration pipeline."""
import numpy as np
import sqlite3
import os

os.makedirs('/app/data', exist_ok=True)

# ---------------------------------------------------------------------------
# 3D phantom volume with smooth features
# ---------------------------------------------------------------------------
shape = (32, 40, 28)
I, J, K = np.mgrid[0:shape[0], 0:shape[1], 0:shape[2]]
I, J, K = I.astype(np.float64), J.astype(np.float64), K.astype(np.float64)
cx, cy, cz = 16.0, 20.0, 14.0

r1 = np.sqrt(((I - cx) / 16) ** 2 + ((J - cy) / 20) ** 2 + ((K - cz) / 14) ** 2)
data = np.exp(-r1 ** 2 * 8)
r2 = np.sqrt(((I - 8) / 5.0) ** 2 + ((J - 10) / 5.0) ** 2 + ((K - 7) / 5.0) ** 2)
data += 0.5 * np.exp(-r2 ** 2 * 4)
data = data.astype(np.float64)

# ---------------------------------------------------------------------------
# Affine matrices
# ---------------------------------------------------------------------------
# RAS-aligned with anisotropic spacing (1.0, 0.8, 1.5) mm
affine_ras = np.array([
    [1.0, 0.0, 0.0, -16.0],
    [0.0, 0.8, 0.0, -16.0],
    [0.0, 0.0, 1.5, -21.0],
    [0.0, 0.0, 0.0,   1.0],
], dtype=np.float64)

# Oblique: 15-degree z-axis rotation applied to RAS affine
theta = np.radians(15.0)
R = np.eye(4, dtype=np.float64)
R[0, 0] = np.cos(theta); R[0, 1] = -np.sin(theta)
R[1, 0] = np.sin(theta); R[1, 1] = np.cos(theta)
affine_oblique = R @ affine_ras

np.save('/app/data/volume.npy', data)
np.save('/app/data/affine_ras.npy', affine_ras)
np.save('/app/data/affine_oblique.npy', affine_oblique)

# ---------------------------------------------------------------------------
# Landmark pairs for registration testing (30-deg z-rotation + translation)
# ---------------------------------------------------------------------------
theta_reg = np.radians(30.0)
R_reg = np.array([
    [np.cos(theta_reg), -np.sin(theta_reg), 0],
    [np.sin(theta_reg),  np.cos(theta_reg), 0],
    [0, 0, 1]
], dtype=np.float64)
t_reg = np.array([5.0, -3.0, 2.0], dtype=np.float64)

src_landmarks = np.array([
    [0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0],
    [0.0, 0.0, 10.0], [5.0, 5.0, 5.0], [3.0, -7.0, 2.0], [-4.0, 6.0, -3.0],
], dtype=np.float64)
tgt_landmarks = (R_reg @ src_landmarks.T).T + t_reg

np.save('/app/data/src_landmarks.npy', src_landmarks)
np.save('/app/data/tgt_landmarks.npy', tgt_landmarks)

# ---------------------------------------------------------------------------
# SQLite metadata database
# ---------------------------------------------------------------------------
conn = sqlite3.connect('/app/metadata.db')
c = conn.cursor()

# Transform ordering constraints
c.execute('''CREATE TABLE transform_constraints (
    id INTEGER PRIMARY KEY,
    step_before TEXT NOT NULL,
    step_after TEXT NOT NULL,
    reason TEXT NOT NULL
)''')
c.executemany('INSERT INTO transform_constraints VALUES (?, ?, ?, ?)', [
    (1, 'orient', 'normalize',
     'Spatial reorientation must precede intensity normalization to avoid interpolation artifacts at flipped volume boundaries'),
    (2, 'orient', 'resample',
     'Orientation must be established before resampling to target spacing'),
    (3, 'resample', 'register',
     'Registration should operate on data already in target spacing'),
    (4, 'orient', 'register',
     'Registration requires consistent orientation between fixed and moving volumes'),
])

# Expected numerical results for debugging
c.execute('''CREATE TABLE expected_results (
    id INTEGER PRIMARY KEY,
    test_name TEXT NOT NULL,
    description TEXT NOT NULL,
    expected_value TEXT NOT NULL
)''')
c.executemany('INSERT INTO expected_results VALUES (?, ?, ?, ?)', [
    (1, 'spacing_ras', 'Voxel spacing from axis-aligned RAS affine', '1.0,0.8,1.5'),
    (2, 'spacing_oblique', 'Voxel spacing from 15-deg oblique affine', '1.0,0.8,1.5'),
    (3, 'axcodes_ras', 'Orientation codes for RAS affine', 'RAS'),
    (4, 'axcodes_oblique', 'Orientation codes for oblique RAS affine', 'RAS'),
    (5, 'resample_2mm_shape', 'Output shape after 2mm isotropic resampling of 32x40x28 volume', '16,16,21'),
    (6, 'resample_1.2mm_shape', 'Output shape after 1.2mm isotropic resampling', '27,27,35'),
    (7, 'identity_resample_maxerr', 'Max error when resampling with identity transform', '0.0'),
    (8, 'correct_pipeline_spacing_key', 'The settings.json key the pipeline resample step should reference', 'target_spacing'),
    (9, 'registration_tre_threshold', 'Maximum acceptable Target Registration Error', '1e-6'),
])

# Ground truth registration parameters
c.execute('''CREATE TABLE reference_data (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    description TEXT NOT NULL
)''')
c.executemany('INSERT INTO reference_data VALUES (?, ?, ?, ?)', [
    (1, 'registration_rotation_deg', '30.0', 'Rotation angle in degrees'),
    (2, 'registration_rotation_axis', 'z', 'Axis of rotation'),
    (3, 'registration_translation', '5.0,-3.0,2.0', 'Translation vector (x,y,z)'),
    (4, 'volume_shape', '32,40,28', 'Shape of test volume'),
    (5, 'affine_spacing', '1.0,0.8,1.5', 'Voxel spacing of RAS affine'),
    (6, 'spacing_norm', 'L2', 'Correct norm for computing voxel spacing from affine columns'),
    (7, 'meshgrid_indexing', 'ij', 'Correct numpy meshgrid indexing for volumetric coordinate grids'),
])

conn.commit()
conn.close()

print("Generated test data and metadata database:")
print(f"  volume.npy: shape={data.shape}, dtype={data.dtype}")
print(f"  affine_ras.npy: spacing=[1.0, 0.8, 1.5]")
print(f"  affine_oblique.npy: 15-deg z-rotation of RAS")
print(f"  src_landmarks.npy: {src_landmarks.shape[0]} source landmarks")
print(f"  tgt_landmarks.npy: {tgt_landmarks.shape[0]} target landmarks")
print(f"  metadata.db: 3 tables (transform_constraints, expected_results, reference_data)")
