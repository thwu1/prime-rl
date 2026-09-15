"""Generate deterministic weight matrices and calibration data for OBQ task."""
import numpy as np
import os

np.random.seed(42)
os.makedirs('/app/data', exist_ok=True)

# 3-layer MLP weights (simulating a pre-trained network)
W0 = np.random.randn(128, 64).astype(np.float64) * 0.1
W1 = np.random.randn(64, 128).astype(np.float64) * 0.08
W2 = np.random.randn(10, 64).astype(np.float64) * 0.12

# Calibration data (256 samples, matching layer 0 input dimension)
X = np.random.randn(256, 64).astype(np.float64)

np.save('/app/data/weights_layer0.npy', W0)
np.save('/app/data/weights_layer1.npy', W1)
np.save('/app/data/weights_layer2.npy', W2)
np.save('/app/data/calibration.npy', X)

print("Generated data files in /app/data/")
for f in sorted(os.listdir('/app/data')):
    arr = np.load(f'/app/data/{f}')
    print(f"  {f}: shape={arr.shape}, dtype={arr.dtype}")
