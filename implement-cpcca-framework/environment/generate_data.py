
import numpy as np
import h5py
import os

rng = np.random.RandomState(42)
n, p, q = 200, 50, 30

# Three coupled temporal signals of decreasing strength
t = np.linspace(0, 4 * np.pi, n)
s1 = np.sin(t)
s2 = np.cos(0.7 * t)
s3 = np.sin(1.3 * t + 0.5)

# Random spatial patterns
px1, py1 = rng.randn(p), rng.randn(q)
px2, py2 = rng.randn(p), rng.randn(q)
px3, py3 = rng.randn(p), rng.randn(q)

# Construct coupled datasets with decreasing signal-to-noise
X_raw = (3.0 * np.outer(s1, px1)
         + 1.5 * np.outer(s2, px2)
         + 0.8 * np.outer(s3, px3)
         + 0.3 * rng.randn(n, p))

Y_raw = (3.0 * np.outer(s1, py1)
         + 1.5 * np.outer(s2, py2)
         + 0.8 * np.outer(s3, py3)
         + 0.3 * rng.randn(n, q))

# Center the data (subtract column means)
X_centered = X_raw - X_raw.mean(axis=0)
Y_centered = Y_raw - Y_raw.mean(axis=0)

os.makedirs('/app/data', exist_ok=True)

with h5py.File('/app/data/fields.h5', 'w') as f:
    f.attrs['description'] = 'Cross-decomposition analysis dataset v3.0'
    f.attrs['normalization'] = 'unbiased'
    f.attrs['n_coupled_signals'] = 3

    # Raw observations (not preprocessed — uncentered)
    obs = f.create_group('observations')
    obs.attrs['processing_level'] = 'raw'
    obs.attrs['centered'] = False
    dx_raw = obs.create_dataset('X', data=X_raw)
    dx_raw.attrs['description'] = 'Raw left field observations'
    dx_raw.attrs['n_samples'] = n
    dx_raw.attrs['n_features'] = p
    dy_raw = obs.create_dataset('Y', data=Y_raw)
    dy_raw.attrs['description'] = 'Raw right field observations'
    dy_raw.attrs['n_samples'] = n
    dy_raw.attrs['n_features'] = q

    # Preprocessed centered anomalies (ready for decomposition)
    prep = f.create_group('preprocessed')
    prep.attrs['processing_level'] = 'centered_anomalies'
    prep.attrs['centered'] = True
    prep.attrs['detrended'] = False
    dleft = prep.create_dataset('left_field', data=X_centered,
                                compression='gzip', compression_opts=4)
    dleft.attrs['shape_convention'] = 'samples_by_features'
    dleft.attrs['n_samples'] = n
    dleft.attrs['n_features'] = p
    dleft.attrs['description'] = 'Centered left field anomalies'
    dright = prep.create_dataset('right_field', data=Y_centered,
                                 compression='gzip', compression_opts=4)
    dright.attrs['shape_convention'] = 'samples_by_features'
    dright.attrs['n_samples'] = n
    dright.attrs['n_features'] = q
    dright.attrs['description'] = 'Centered right field anomalies'

print(f"Data generated: X {X_centered.shape}, Y {Y_centered.shape}")
print(f"Saved to /app/data/fields.h5")
