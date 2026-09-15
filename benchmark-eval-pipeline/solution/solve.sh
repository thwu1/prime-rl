#!/bin/bash


pip3 install numpy==1.26.4 scipy==1.13.1 Pillow==10.4.0 -q

# Deploy solution implementation
cp /solution/evaluator_impl.py /app/evaluator.py

# Verify the implementation loads and core functions work
python3 -c "
import sys
sys.path.insert(0, '/app')
from evaluator import (photometric_loss, ssim_score, composite_distance,
                        multi_view_aggregate, swiss_tournament, trimmed_mean,
                        bca_bootstrap_ci, evaluate_benchmark, load_config,
                        init_cache)
import numpy as np

# Smoke tests
img = np.full((32, 32, 3), 128, dtype=np.uint8)
pl = photometric_loss(img, img.copy())
assert pl == 0.0, f'photometric_loss of identical images should be 0, got {pl}'

ss = ssim_score(img, img.copy())
assert abs(ss - 1.0) < 1e-6, f'ssim of identical images should be 1.0, got {ss}'

config = load_config('/app/config.toml')
assert config['metrics']['alpha'] == 0.5, 'Config alpha should be 0.5'

conn = init_cache('/tmp/smoke_cache.db')
conn.close()

assert trimmed_mean([]) == 0.0
assert bca_bootstrap_ci([]) == (0.0, 0.0)
assert bca_bootstrap_ci([3.14]) == (3.14, 3.14)

result = swiss_tournament([], np.array([0.0]), 3, lambda c,t: abs(c[0]-t[0]))
assert result == []

print('All smoke tests passed - solution deployed successfully')
"
