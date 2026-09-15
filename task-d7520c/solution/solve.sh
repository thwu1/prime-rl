#!/bin/bash

# Install solution dependencies
pip3 install scipy==1.14.1 numpy==2.1.3 -q

# Deploy fixed implementations
cp /solution/quantization_impl.py /app/nf4_quant/quantization.py
cp /solution/memory_impl.py /app/nf4_quant/memory.py

# Smoke test: verify all fixes produce correct results
python3 -c "
import sys
sys.path.insert(0, '/app')
import torch

from nf4_quant.quantization import create_nf4_map, quantize_nf4, dequantize_nf4
from nf4_quant.quantization import double_quantize, double_dequantize
from nf4_quant.memory import bits_per_parameter, compute_total_params

# Verify NF4 map: 16 unique levels, asymmetric
nf4 = create_nf4_map()
unique = torch.unique(nf4)
assert len(unique) == 16, f'Expected 16 unique levels, got {len(unique)}'
neg = (unique < -1e-8).sum().item()
pos = (unique > 1e-8).sum().item()
assert {neg, pos} == {7, 8}, f'Expected {{7,8}} asymmetry, got ({neg}, {pos})'

# Verify roundtrip accuracy
torch.manual_seed(0)
t = torch.randn(256, 256)
q, s = quantize_nf4(t, blocksize=64)
r = dequantize_nf4(q, s)
err = (t - r).abs().mean().item()
assert err < 0.10, f'Roundtrip error {err} too high'

# Verify double quantization recovery
dq, ds = double_quantize(s['absmax'], blocksize=256)
rec = double_dequantize(dq, ds)
dq_err = (s['absmax'] - rec).abs().mean().item()
dq_range = (s['absmax'].max() - s['absmax'].min()).item()
assert dq_err / dq_range < 0.004, f'DQ error ratio {dq_err/dq_range} too high'

# Verify memory calculations
assert bits_per_parameter(4, 64, False) == 4.5
assert abs(bits_per_parameter(4, 64, True, 256) - 4.126953125) < 1e-9
assert compute_total_params({'hidden_size': 4096, 'num_layers': 32, 'num_heads': 32, 'intermediate_size': 11008, 'vocab_size': 32000}) == 6738149376

print('All smoke tests passed.')
"
