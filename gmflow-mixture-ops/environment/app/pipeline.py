#!/usr/bin/env python3

"""
Bayesian inference pipeline using Gaussian mixture operations.
Constructs a GM prior, performs Bayesian updates, combines posteriors,
reduces the combined posterior, and writes summary statistics and
quality metrics to /app/results.json.
"""

import json
import math
import torch
from gm_ops import (
    gm_nll_loss, gm_to_iso_gaussian, gm_mul_iso_gaussian,
    gm_logprob, gm_mul_gm, gm_kl_div, gm_reduce
)


def create_prior():
    """Create a 4-component 2D Gaussian mixture prior."""
    return {
        'means': torch.tensor([[
            [-2.0, -2.0], [2.0, -2.0], [-2.0, 2.0], [2.0, 2.0]
        ]]),
        'logstds': torch.tensor([[[0.0]]]),
        'logweights': torch.log_softmax(torch.zeros(1, 4, 1), dim=1),
    }


def run():
    torch.manual_seed(0)

    # 1. Create 4-component 2D GM prior
    prior = create_prior()

    # 2. Bayesian update with first observation (non-unit powers)
    obs1 = {'mean': torch.tensor([[1.0, 1.0]]), 'var': torch.tensor([[1.5]])}
    posterior1 = gm_mul_iso_gaussian(prior, obs1, gm_power=0.7, gaussian_power=1.3)

    # 3. Bayesian update with second observation (different powers)
    obs2 = {'mean': torch.tensor([[-1.0, 0.5]]), 'var': torch.tensor([[2.0]])}
    posterior2 = gm_mul_iso_gaussian(prior, obs2, gm_power=0.5, gaussian_power=1.5)

    # 4. Combine posteriors via GM product (K1*K2 = 16 components)
    combined = gm_mul_gm(posterior1, posterior2)

    # 5. Reduce combined posterior to 6 components
    reduced = gm_reduce(combined, target_k=6)

    # 6. Moment-matched summary statistics of reduced posterior
    iso = gm_to_iso_gaussian(reduced)

    # 7. KL divergence from reduced posterior to prior
    kl_to_prior = gm_kl_div(reduced, prior, n_samples=512)

    # 8. Reduction quality: KL from full to reduced posterior
    kl_reduction = gm_kl_div(combined, reduced, n_samples=512)

    # 9. Evaluate at a test point
    test_point = torch.tensor([[0.5, 0.5]])
    nll = gm_nll_loss(reduced, test_point)
    logp = gm_logprob(reduced, test_point.unsqueeze(1))

    # 10. Write results
    results = {
        'posterior_mean': iso['mean'].squeeze(0).tolist(),
        'posterior_var': iso['var'].item(),
        'kl_to_prior': kl_to_prior.item(),
        'kl_reduction_loss': kl_reduction.item(),
        'nll_at_test_point': nll.item(),
        'logprob_at_test_point': logp.squeeze().item(),
        'num_components_full': int(combined['means'].shape[1]),
        'num_components_reduced': int(reduced['means'].shape[1]),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Pipeline completed. Results written to /app/results.json")
    for k, v in results.items():
        print(f"  {k}: {v}")

    return results


if __name__ == '__main__':
    run()
