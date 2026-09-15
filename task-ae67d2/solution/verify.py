"""Verify the solution works end-to-end."""
import sys
sys.path.insert(0, "/app")

import json
import numpy as np
import stim

from dem_to_matrices import detector_error_model_to_check_matrices
from decoder import SyndromeDecoder

# Load config
with open("/app/config.json") as f:
    config = json.load(f)

# Test matrix conversion on small DEM
dem_small = stim.DetectorErrorModel(
    "error(0.1) D0 D3 L0 L1 ^ D1 D2 L1\n"
    "error(0.15) D0 D3 L0 L1 ^ D1 D2 L1\n"
    "error(0.2) D0 D3 L0 L1\n"
    "error(0.3) D1 D2 L1\n"
    "error(0.4) D1 D2 L1\n"
)
mats = detector_error_model_to_check_matrices(dem_small)
assert mats.check_matrix.shape == (4, 3), f"Bad check_matrix shape: {mats.check_matrix.shape}"
assert np.allclose(mats.priors, [0.22, 0.2, 0.46]), f"Bad priors: {mats.priors}"
print("Matrix conversion: OK")

# Test decoder on surface code
dem = stim.DetectorErrorModel.from_file("/app/surface_code.dem")
decoder = SyndromeDecoder(dem)

shot_data = stim.read_shot_data_file(
    path="/app/shots.b8",
    format="b8",
    num_detectors=config["num_detectors"],
    num_observables=config["num_observables"],
)
shots = shot_data[:, :config["num_detectors"]]
observables = shot_data[:, config["num_detectors"]:]

predictions = decoder.decode_batch(shots)
errors = int(np.sum(np.any(predictions != observables, axis=1)))
print(f"Decoder errors: {errors}/{config['num_shots']}")
print("Solution verification: OK")
