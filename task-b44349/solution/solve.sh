#!/bin/bash

# Install solution dependencies
pip3 install numpy==2.1.3 -q

# Deploy the corrected score engine
cp /solution/score_engine_fixed.py /app/score_engine.py

# Validate the fix by running computational checks
python3 -c "
import sys, torch, math
sys.path.insert(0, '/app')
from score_engine import gm_score, gm_score_divergence, gm_kernel_stein_discrepancy

# Helper to build GM dicts
def mk(means, logstd, logweights):
    m = torch.tensor(means, dtype=torch.float64).unsqueeze(0)
    ls = torch.tensor([[[logstd]]], dtype=torch.float64)
    lw = torch.tensor([logweights], dtype=torch.float64)
    return {'means': m, 'logstds': ls, 'logweights': lw}

# 1. Verify tail stability (the core numerical fix)
gm = mk([[0.0, 0.0], [1.0, 1.0]], 0.0, [0.0, 0.0])
x_tail = torch.tensor([[50.0, 50.0]], dtype=torch.float64)
s = gm_score(gm, x_tail)
assert torch.isfinite(s).all(), f'Score not finite in tails: {s}'
print('PASS: tail stability')

# 2. Verify score at mean is zero
gm1 = mk([[0.0, 0.0]], 0.0, [0.0])
x0 = torch.tensor([[0.0, 0.0]], dtype=torch.float64)
s0 = gm_score(gm1, x0)
assert (s0.abs() < 1e-6).all(), f'Score at mean not zero: {s0}'
print('PASS: score at mean')

# 3. Verify divergence for single Gaussian: -D/sigma^2 = -2
x = torch.tensor([[0.5, -0.3]], dtype=torch.float64)
div_s = gm_score_divergence(gm1, x)
assert abs(div_s.item() - (-2.0)) < 1e-4, f'Divergence incorrect: {div_s}'
print('PASS: divergence analytical')

# 4. Verify divergence at midpoint between modes
gm2 = mk([[-1.0, 0.0], [1.0, 0.0]], 0.0, [0.0, 0.0])
x_mid = torch.tensor([[0.0, 0.0]], dtype=torch.float64)
div_mid = gm_score_divergence(gm2, x_mid)
assert abs(div_mid.item() - (-1.0)) < 1e-4, f'Midpoint divergence wrong: {div_mid}'
print('PASS: divergence at midpoint')

# 5. Verify KSD with manually generated samples (no dependency on gm_sample)
torch.manual_seed(42)
samples = torch.randn(1, 300, 2, dtype=torch.float64)  # ~ N(0,I)
ksd = gm_kernel_stein_discrepancy(gm1, samples)
assert torch.isfinite(ksd).all(), f'KSD not finite: {ksd}'
assert ksd.item() < 0.1, f'KSD for matching dist too large: {ksd}'
print('PASS: KSD self-test')

# 6. Verify KSD detects mean shift
shifted_samples = samples + 5.0
ksd_shifted = gm_kernel_stein_discrepancy(gm1, shifted_samples)
assert ksd_shifted.item() > 0.5, f'KSD should detect shift: {ksd_shifted}'
print('PASS: KSD mean shift detection')

# 7. Stein identity check with manual samples
torch.manual_seed(42)
N = 3000
test_samples = torch.randn(N, 2, dtype=torch.float64)  # samples from N(0,I)
gm_exp = {
    'means': gm1['means'].expand(N, -1, -1),
    'logstds': gm1['logstds'].expand(N, -1, -1),
    'logweights': gm1['logweights'].expand(N, -1),
}
s_all = gm_score(gm_exp, test_samples)
d_all = gm_score_divergence(gm_exp, test_samples)
stein = (d_all + (s_all**2).sum(dim=-1)).mean().item()
assert abs(stein) < 0.15, f'Stein identity violated: {stein}'
print('PASS: Stein identity')

print('All computational validations passed')
"
