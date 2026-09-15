#!/bin/bash

pip3 install stim==1.14.0 numpy==1.26.4 scipy==1.13.1 networkx==3.3 -q

cp /solution/qec_pipeline.py /app/qec_pipeline.py

echo "Solution installed at /app/qec_pipeline.py"
python3 -c "
import sys
sys.path.insert(0, '/app')
from qec_pipeline import DemMatrices, dem_to_matrices, Decoder
import stim, numpy as np

# Quick smoke test
dem = stim.DetectorErrorModel('error(0.1) D0 D1\nerror(0.2) D1 D2\nerror(0.15) D0 L0\nerror(0.25) D2 L0')
mats = dem_to_matrices(dem)
print(f'check_matrix shape: {mats.check_matrix.shape}')
print(f'priors: {mats.priors}')

decoder = Decoder(dem)
pred = decoder.decode(np.array([1, 0, 0], dtype=np.uint8))
print(f'Decode [1,0,0] -> {pred}')
assert pred[0] == 1, 'Decoder failed smoke test'
print('Smoke test passed.')
"
