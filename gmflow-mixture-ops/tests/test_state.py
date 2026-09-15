
import sys
sys.path.insert(0, '/app')

import json
import math
import os
import subprocess

import pytest
import torch
import numpy as np
from scipy.special import logsumexp as scipy_logsumexp

from gm_ops import (
    gm_nll_loss, gm_to_iso_gaussian, gm_mul_iso_gaussian,
    gm_logprob, gm_mul_gm, gm_kl_div, gm_reduce
)


# ============================================================
# Numpy reference implementations
# ============================================================

def ref_nll(means, logstds, logweights, sample, eps=1e-4):
    """Numpy reference for gm_nll_loss."""
    inverse_stds = np.clip(np.exp(-logstds), a_min=None, a_max=1.0 / eps)
    diff = sample[:, np.newaxis, :] - means
    diff_weighted = diff * inverse_stds
    gaussian_ll = (-0.5 * diff_weighted ** 2 - logstds).sum(axis=-1)
    nll = -scipy_logsumexp(
        gaussian_ll + logweights.squeeze(-1), axis=-1
    )
    return nll


def ref_logprob(means, logstds, logweights, samples):
    """Numpy reference for gm_logprob."""
    D = means.shape[-1]
    const = -0.5 * D * np.log(2.0 * np.pi)
    inverse_stds = np.exp(-logstds)
    diff = (
        samples[:, :, np.newaxis, :]
        - means[:, np.newaxis, :, :]
    )
    diff_weighted = diff * inverse_stds[:, np.newaxis, :, :]
    per_dim = -0.5 * diff_weighted ** 2 - logstds[:, np.newaxis, :, :]
    gaussian_lp = per_dim.sum(axis=-1) + const
    lw = logweights.squeeze(-1)[:, np.newaxis, :]
    logprob = scipy_logsumexp(gaussian_lp + lw, axis=-1)
    return logprob


def ref_gm_mul_gm(means1, logstds1, logweights1, means2, logstds2, logweights2):
    """Numpy reference for gm_mul_gm."""
    bs, K1, D = means1.shape
    K2 = means2.shape[1]

    var1 = np.exp(2 * logstds1)  # (bs, 1, 1)
    var2 = np.exp(2 * logstds2)  # (bs, 1, 1)
    norm_factor = var1 + var2    # (bs, 1, 1)

    # New log-std (shared)
    new_logstd = logstds1 + logstds2 - 0.5 * np.log(norm_factor)

    # All K1*K2 pair means
    m1 = means1[:, :, np.newaxis, :]  # (bs, K1, 1, D)
    m2 = means2[:, np.newaxis, :, :]  # (bs, 1, K2, D)

    new_means = (
        var2[..., np.newaxis] * m1 + var1[..., np.newaxis] * m2
    ) / norm_factor[..., np.newaxis]
    new_means = new_means.reshape(bs, K1 * K2, D)

    # Weight deltas
    diffs = m1 - m2  # (bs, K1, K2, D)
    sq_dists = (diffs ** 2).sum(axis=-1)  # (bs, K1, K2)
    deltas = -sq_dists / (2 * norm_factor)  # (bs, K1, K2)

    lw1 = logweights1.squeeze(-1)[:, :, np.newaxis]  # (bs, K1, 1)
    lw2 = logweights2.squeeze(-1)[:, np.newaxis, :]  # (bs, 1, K2)
    raw_lw = (lw1 + lw2 + deltas).reshape(bs, K1 * K2)

    # Log-softmax
    max_lw = raw_lw.max(axis=-1, keepdims=True)
    new_lw = raw_lw - max_lw - np.log(
        np.exp(raw_lw - max_lw).sum(axis=-1, keepdims=True)
    )
    new_lw = new_lw[:, :, np.newaxis]  # (bs, K1*K2, 1)

    return new_means, new_logstd, new_lw


# ============================================================
# Tests: gm_nll_loss (should be correct — verify not broken)
# ============================================================

class TestGMNLLLoss:

    def test_single_gaussian_at_mean(self):
        gm = {
            'means': torch.tensor([[[0.0]]]),
            'logstds': torch.tensor([[[0.0]]]),
            'logweights': torch.tensor([[[0.0]]]),
        }
        loss = gm_nll_loss(gm, torch.tensor([[0.0]]))
        torch.testing.assert_close(loss, torch.tensor([0.0]), atol=1e-6, rtol=1e-6)

    def test_against_numpy_reference(self):
        torch.manual_seed(42)
        means = torch.randn(2, 3, 4)
        logstds = torch.randn(2, 1, 1) * 0.5
        logweights = torch.randn(2, 3, 1)
        sample = torch.randn(2, 4)

        gm = {'means': means, 'logstds': logstds, 'logweights': logweights}
        result = gm_nll_loss(gm, sample)
        ref = ref_nll(
            means.numpy(), logstds.numpy(),
            logweights.numpy(), sample.numpy(),
        )
        torch.testing.assert_close(
            result, torch.from_numpy(ref).float(), atol=1e-4, rtol=1e-4,
        )


# ============================================================
# Tests: gm_logprob (should be correct — verify not broken)
# ============================================================

class TestGMLogprob:

    def test_standard_normal_at_zero(self):
        gm = {
            'means': torch.tensor([[[0.0]]]),
            'logstds': torch.tensor([[[0.0]]]),
            'logweights': torch.tensor([[[0.0]]]),
        }
        result = gm_logprob(gm, torch.tensor([[[0.0]]]))
        expected = -0.5 * math.log(2 * math.pi)
        torch.testing.assert_close(
            result, torch.tensor([[expected]]), atol=1e-4, rtol=1e-4,
        )

    def test_against_numpy_reference(self):
        torch.manual_seed(123)
        means = torch.randn(2, 3, 4)
        logstds = torch.randn(2, 1, 1) * 0.5
        logweights = torch.log_softmax(torch.randn(2, 3, 1), dim=1)
        samples = torch.randn(2, 5, 4)

        gm = {'means': means, 'logstds': logstds, 'logweights': logweights}
        result = gm_logprob(gm, samples)
        ref = ref_logprob(
            means.numpy(), logstds.numpy(),
            logweights.numpy(), samples.numpy(),
        )
        torch.testing.assert_close(
            result, torch.from_numpy(ref).float(), atol=1e-4, rtol=1e-4,
        )


# ============================================================
# Tests: gm_to_iso_gaussian (BUG: sum vs mean over dims)
# ============================================================

class TestGMToIsoGaussian:

    def test_variance_averaging_over_dimensions(self):
        """D=3 case: between-component variance must be AVERAGED over dims, not summed.

        With the bug (sum), var = 12 + e ≈ 14.72.
        Correct (mean): var = 4 + e ≈ 6.72.
        """
        gm = {
            'means': torch.tensor([[[1.0, 2.0, 3.0], [5.0, 6.0, 7.0]]]),
            'logstds': torch.tensor([[[0.5]]]),
            'logweights': torch.log_softmax(torch.zeros(1, 2, 1), dim=1),
        }
        result = gm_to_iso_gaussian(gm)

        # Expected mean = midpoint
        torch.testing.assert_close(
            result['mean'], torch.tensor([[3.0, 4.0, 5.0]]), atol=1e-4, rtol=1e-4,
        )

        # Between-component var per dim = 4.0 (each dim has equal spread)
        # Mean over D=3 dims: 4.0
        # Within-component var = exp(2*0.5) = e ≈ 2.7183
        # Total = 4.0 + 2.7183 ≈ 6.7183
        expected_var = 4.0 + math.exp(1.0)
        torch.testing.assert_close(
            result['var'], torch.tensor([[expected_var]]), atol=1e-3, rtol=1e-3,
        )

    def test_single_component(self):
        """Single component: var = within-component variance only."""
        gm = {
            'means': torch.tensor([[[5.0, 3.0]]]),
            'logstds': torch.tensor([[[0.5]]]),
            'logweights': torch.tensor([[[0.0]]]),
        }
        result = gm_to_iso_gaussian(gm)
        torch.testing.assert_close(
            result['mean'], torch.tensor([[5.0, 3.0]]), atol=1e-4, rtol=1e-4,
        )
        expected_var = math.exp(2 * 0.5)
        torch.testing.assert_close(
            result['var'], torch.tensor([[expected_var]]), atol=1e-4, rtol=1e-4,
        )

    def test_output_shapes(self):
        gm = {
            'means': torch.randn(3, 5, 4),
            'logstds': torch.randn(3, 1, 1),
            'logweights': torch.log_softmax(torch.randn(3, 5, 1), dim=1),
        }
        result = gm_to_iso_gaussian(gm)
        assert result['mean'].shape == (3, 4)
        assert result['var'].shape == (3, 1)


# ============================================================
# Tests: gm_mul_iso_gaussian (BUG: inverted power ratio)
# ============================================================

class TestGMMulIsoGaussian:

    def test_asymmetric_powers(self):
        """With gm_power=0.5, gaussian_power=2.0, power_ratio should be 4.0.

        Correct: means shift strongly toward gaussian mean [2,2].
          comp 0: [1.6, 1.6], comp 1: [2.4, 2.4]
        Buggy (inverted ratio=0.25): means barely shift.
          comp 0: [0.4, 0.4], comp 1: [3.6, 3.6]
        """
        log_half = math.log(0.5)
        gm = {
            'means': torch.tensor([[[0.0, 0.0], [4.0, 4.0]]]),
            'logstds': torch.tensor([[[0.0]]]),
            'logweights': torch.tensor([[[log_half], [log_half]]]),
        }
        gaussian = {'mean': torch.tensor([[2.0, 2.0]]),
                     'var': torch.tensor([[1.0]])}
        result = gm_mul_iso_gaussian(gm, gaussian, gm_power=0.5, gaussian_power=2.0)

        # Correct power_ratio = 2.0 / 0.5 = 4.0
        # norm_factor = 1.0 + 4.0 * 1.0 = 5.0
        # out_means[0] = (1.0*[0,0] + 4.0*[2,2]) / 5.0 = [1.6, 1.6]
        # out_means[1] = (1.0*[4,4] + 4.0*[2,2]) / 5.0 = [2.4, 2.4]
        expected_means = torch.tensor([[[1.6, 1.6], [2.4, 2.4]]])
        torch.testing.assert_close(
            result['means'], expected_means, atol=1e-4, rtol=1e-4,
        )

    def test_symmetric_powers(self):
        """Equal powers: should work correctly regardless of ratio direction."""
        log_half = math.log(0.5)
        gm = {
            'means': torch.tensor([[[0.0, 0.0], [2.0, 2.0]]]),
            'logstds': torch.tensor([[[0.0]]]),
            'logweights': torch.tensor([[[log_half], [log_half]]]),
        }
        gaussian = {'mean': torch.tensor([[1.0, 1.0]]),
                     'var': torch.tensor([[2.0]])}
        result = gm_mul_iso_gaussian(gm, gaussian, 1.0, 1.0)

        # norm_factor = 2 + 1 = 3
        expected_means = torch.tensor([[[1.0 / 3, 1.0 / 3], [5.0 / 3, 5.0 / 3]]])
        torch.testing.assert_close(
            result['means'], expected_means, atol=1e-4, rtol=1e-4,
        )

    def test_logweights_normalized(self):
        torch.manual_seed(77)
        gm = {
            'means': torch.randn(2, 4, 3),
            'logstds': torch.randn(2, 1, 1),
            'logweights': torch.log_softmax(torch.randn(2, 4, 1), dim=1),
        }
        gaussian = {'mean': torch.randn(2, 3), 'var': torch.ones(2, 1) * 2}
        result = gm_mul_iso_gaussian(gm, gaussian, 0.8, 1.2)
        weight_sums = result['logweights'].squeeze(-1).exp().sum(dim=1)
        torch.testing.assert_close(
            weight_sums, torch.ones(2), atol=1e-4, rtol=1e-4,
        )


# ============================================================
# Tests: gm_mul_gm (NOT IMPLEMENTED — must be created)
# ============================================================

class TestGMMulGM:

    def test_output_component_count(self):
        """K1=2, K2=3 should produce 6 components."""
        gm1 = {
            'means': torch.randn(1, 2, 4),
            'logstds': torch.randn(1, 1, 1),
            'logweights': torch.log_softmax(torch.randn(1, 2, 1), dim=1),
        }
        gm2 = {
            'means': torch.randn(1, 3, 4),
            'logstds': torch.randn(1, 1, 1),
            'logweights': torch.log_softmax(torch.randn(1, 3, 1), dim=1),
        }
        result = gm_mul_gm(gm1, gm2)
        assert result['means'].shape == (1, 6, 4)
        assert result['logstds'].shape == (1, 1, 1)
        assert result['logweights'].shape == (1, 6, 1)

    def test_means_against_numpy_reference(self):
        """Compare means against numpy reference implementation."""
        gm1 = {
            'means': torch.tensor([[[0.0, 0.0], [2.0, 0.0]]]),
            'logstds': torch.tensor([[[0.0]]]),
            'logweights': torch.log_softmax(torch.zeros(1, 2, 1), dim=1),
        }
        gm2 = {
            'means': torch.tensor([[[0.0, 0.0], [0.0, 2.0]]]),
            'logstds': torch.tensor([[[0.5]]]),
            'logweights': torch.log_softmax(torch.zeros(1, 2, 1), dim=1),
        }
        result = gm_mul_gm(gm1, gm2)

        ref_means, ref_logstd, ref_lw = ref_gm_mul_gm(
            gm1['means'].numpy(), gm1['logstds'].numpy(), gm1['logweights'].numpy(),
            gm2['means'].numpy(), gm2['logstds'].numpy(), gm2['logweights'].numpy(),
        )

        torch.testing.assert_close(
            result['means'],
            torch.from_numpy(ref_means).float(),
            atol=1e-4, rtol=1e-4,
        )
        torch.testing.assert_close(
            result['logstds'],
            torch.from_numpy(ref_logstd).float(),
            atol=1e-4, rtol=1e-4,
        )

    def test_logweights_against_numpy_reference(self):
        """Compare logweights against numpy reference."""
        torch.manual_seed(99)
        gm1 = {
            'means': torch.randn(2, 3, 4),
            'logstds': torch.randn(2, 1, 1) * 0.3,
            'logweights': torch.log_softmax(torch.randn(2, 3, 1), dim=1),
        }
        gm2 = {
            'means': torch.randn(2, 2, 4),
            'logstds': torch.randn(2, 1, 1) * 0.3,
            'logweights': torch.log_softmax(torch.randn(2, 2, 1), dim=1),
        }
        result = gm_mul_gm(gm1, gm2)

        ref_means, ref_logstd, ref_lw = ref_gm_mul_gm(
            gm1['means'].numpy(), gm1['logstds'].numpy(), gm1['logweights'].numpy(),
            gm2['means'].numpy(), gm2['logstds'].numpy(), gm2['logweights'].numpy(),
        )

        assert result['means'].shape == (2, 6, 4)
        torch.testing.assert_close(
            result['logweights'],
            torch.from_numpy(ref_lw).float(),
            atol=1e-4, rtol=1e-4,
        )

    def test_logweights_normalized(self):
        """Output logweights exp should sum to 1 over components."""
        gm1 = {
            'means': torch.randn(2, 3, 4),
            'logstds': torch.randn(2, 1, 1),
            'logweights': torch.log_softmax(torch.randn(2, 3, 1), dim=1),
        }
        gm2 = {
            'means': torch.randn(2, 4, 4),
            'logstds': torch.randn(2, 1, 1),
            'logweights': torch.log_softmax(torch.randn(2, 4, 1), dim=1),
        }
        result = gm_mul_gm(gm1, gm2)
        weight_sums = result['logweights'].squeeze(-1).exp().sum(dim=1)
        torch.testing.assert_close(
            weight_sums, torch.ones(2), atol=1e-4, rtol=1e-4,
        )

    def test_identical_gms_product(self):
        """Product of a GM with itself: means should shift toward center."""
        gm = {
            'means': torch.tensor([[[0.0, 0.0], [4.0, 0.0]]]),
            'logstds': torch.tensor([[[0.0]]]),  # sigma=1
            'logweights': torch.log_softmax(torch.zeros(1, 2, 1), dim=1),
        }
        result = gm_mul_gm(gm, gm)
        # 4 output components; the (0,0) and (1,1) pairs should have
        # means at the original locations (0,0) and (4,0),
        # while (0,1) and (1,0) should have means at (2,0)
        assert result['means'].shape == (1, 4, 2)

        # var1=var2=1, norm_factor=2
        # Cross means: (1*[0,0]+1*[4,0])/2 = [2,0] and (1*[4,0]+1*[0,0])/2 = [2,0]
        # Self means: (1*[0,0]+1*[0,0])/2 = [0,0] and (1*[4,0]+1*[4,0])/2 = [4,0]
        expected_means = torch.tensor([[[0.0, 0.0], [2.0, 0.0], [2.0, 0.0], [4.0, 0.0]]])
        torch.testing.assert_close(
            result['means'], expected_means, atol=1e-4, rtol=1e-4,
        )


# ============================================================
# Tests: gm_reduce (NOT IMPLEMENTED — must be designed)
# ============================================================

class TestGMReduce:

    def test_output_component_count(self):
        """Reducing K=8 to target_k=4 should produce 4 components."""
        torch.manual_seed(10)
        gm = {
            'means': torch.randn(1, 8, 3),
            'logstds': torch.randn(1, 1, 1),
            'logweights': torch.log_softmax(torch.randn(1, 8, 1), dim=1),
        }
        result = gm_reduce(gm, target_k=4)
        assert result['means'].shape == (1, 4, 3)
        assert result['logstds'].shape == (1, 1, 1)
        assert result['logweights'].shape == (1, 4, 1)

    def test_weights_normalized(self):
        """Output weights must sum to 1."""
        torch.manual_seed(11)
        gm = {
            'means': torch.randn(2, 6, 4),
            'logstds': torch.randn(2, 1, 1),
            'logweights': torch.log_softmax(torch.randn(2, 6, 1), dim=1),
        }
        result = gm_reduce(gm, target_k=3)
        weight_sums = result['logweights'].squeeze(-1).exp().sum(dim=1)
        torch.testing.assert_close(
            weight_sums, torch.ones(2), atol=1e-4, rtol=1e-4,
        )

    def test_mean_preservation(self):
        """The overall mean of the reduced mixture must match the original exactly."""
        torch.manual_seed(42)
        gm = {
            'means': torch.randn(2, 8, 3),
            'logstds': torch.randn(2, 1, 1),
            'logweights': torch.log_softmax(torch.randn(2, 8, 1), dim=1),
        }

        # Original mean
        orig_weights = gm['logweights'].exp()
        orig_mean = (orig_weights * gm['means']).sum(dim=1)

        result = gm_reduce(gm, target_k=3)

        # Reduced mean
        red_weights = result['logweights'].exp()
        red_mean = (red_weights * result['means']).sum(dim=1)

        torch.testing.assert_close(orig_mean, red_mean, atol=1e-3, rtol=1e-3)

    def test_preserves_logstds(self):
        """Shared log-std must be preserved unchanged."""
        logstds = torch.tensor([[[0.7]]])
        gm = {
            'means': torch.randn(1, 6, 3),
            'logstds': logstds,
            'logweights': torch.log_softmax(torch.randn(1, 6, 1), dim=1),
        }
        result = gm_reduce(gm, target_k=3)
        torch.testing.assert_close(result['logstds'], logstds)

    def test_close_components_merged(self):
        """Nearby components should be merged before distant ones."""
        gm = {
            'means': torch.tensor([[[0.0, 0.0], [0.01, 0.01],
                                     [10.0, 10.0], [10.01, 10.01]]]),
            'logstds': torch.tensor([[[0.0]]]),
            'logweights': torch.log_softmax(torch.zeros(1, 4, 1), dim=1),
        }
        result = gm_reduce(gm, target_k=2)

        # The two resulting means should be near [0.005, 0.005] and [10.005, 10.005]
        sorted_means = result['means'][0][result['means'][0, :, 0].argsort()]
        torch.testing.assert_close(
            sorted_means[0], torch.tensor([0.005, 0.005]), atol=0.01, rtol=0.01
        )
        torch.testing.assert_close(
            sorted_means[1], torch.tensor([10.005, 10.005]), atol=0.01, rtol=0.01
        )

    def test_kl_divergence_bounded(self):
        """KL divergence from original to reduced should be bounded
        when merging very close components."""
        gm = {
            'means': torch.tensor([[[0.0, 0.0], [0.1, 0.1],
                                     [3.0, 3.0], [3.1, 3.1],
                                     [6.0, 0.0], [6.1, 0.1]]]),
            'logstds': torch.tensor([[[0.0]]]),
            'logweights': torch.log_softmax(torch.zeros(1, 6, 1), dim=1),
        }
        result = gm_reduce(gm, target_k=3)

        # KL divergence between original and reduced should be small
        # because merged pairs are very close (distance ~0.14)
        kl = gm_kl_div(gm, result, n_samples=1024)
        assert kl.item() < 0.5, (
            f"KL divergence too high: {kl.item():.4f}. "
            f"Expected < 0.5 for merging very close components."
        )

    def test_no_reduction_needed(self):
        """If target_k >= K, return a GM with same number of components."""
        torch.manual_seed(12)
        gm = {
            'means': torch.randn(1, 3, 2),
            'logstds': torch.randn(1, 1, 1),
            'logweights': torch.log_softmax(torch.randn(1, 3, 1), dim=1),
        }
        result = gm_reduce(gm, target_k=5)
        assert result['means'].shape[1] == 3  # unchanged

    def test_batch_dimension(self):
        """Reduction must work correctly across batch dimension."""
        torch.manual_seed(13)
        gm = {
            'means': torch.randn(3, 10, 2),
            'logstds': torch.randn(3, 1, 1),
            'logweights': torch.log_softmax(torch.randn(3, 10, 1), dim=1),
        }
        result = gm_reduce(gm, target_k=4)
        assert result['means'].shape == (3, 4, 2)
        assert result['logweights'].shape == (3, 4, 1)

        # Verify mean preservation for each batch element
        orig_weights = gm['logweights'].exp()
        orig_mean = (orig_weights * gm['means']).sum(dim=1)
        red_weights = result['logweights'].exp()
        red_mean = (red_weights * result['means']).sum(dim=1)
        torch.testing.assert_close(orig_mean, red_mean, atol=1e-3, rtol=1e-3)


# ============================================================
# Tests: End-to-end pipeline
# ============================================================

class TestPipeline:

    @classmethod
    def setup_class(cls):
        """Run the pipeline once for all pipeline tests."""
        result = subprocess.run(
            ['python3', '/app/pipeline.py'],
            capture_output=True, text=True, cwd='/app',
            timeout=60,
        )
        cls.returncode = result.returncode
        cls.stderr = result.stderr

        cls.results_path = '/app/results.json'
        if os.path.exists(cls.results_path):
            with open(cls.results_path) as f:
                cls.results = json.load(f)
        else:
            cls.results = None

    def test_pipeline_succeeded(self):
        assert self.returncode == 0, (
            f"Pipeline failed with return code {self.returncode}.\n"
            f"stderr: {self.stderr}"
        )

    def test_results_exist(self):
        assert self.results is not None, "results.json was not created"

    def test_results_structure(self):
        assert self.results is not None
        for key in ['posterior_mean', 'posterior_var', 'kl_to_prior',
                     'kl_reduction_loss', 'nll_at_test_point',
                     'logprob_at_test_point', 'num_components_full',
                     'num_components_reduced']:
            assert key in self.results, f"Missing key: {key}"

    def test_num_components_full(self):
        """Combined posterior should have 4*4 = 16 components."""
        assert self.results is not None
        assert self.results['num_components_full'] == 16

    def test_num_components_reduced(self):
        """Reduced posterior should have exactly 6 components."""
        assert self.results is not None
        assert self.results['num_components_reduced'] == 6

    def test_kl_reduction_bounded(self):
        """KL from full to reduced posterior should be bounded."""
        assert self.results is not None
        assert self.results['kl_reduction_loss'] < 1.0, (
            f"KL reduction loss too high: {self.results['kl_reduction_loss']}"
        )

    def test_nll_logprob_consistency(self):
        """nll + logprob must equal -D/2 * log(2*pi) for D=2."""
        assert self.results is not None
        nll = self.results['nll_at_test_point']
        logp = self.results['logprob_at_test_point']
        expected = -math.log(2 * math.pi)  # D=2
        assert abs((nll + logp) - expected) < 1e-3, (
            f"nll({nll}) + logprob({logp}) = {nll + logp}, "
            f"expected {expected}"
        )

    def test_kl_to_prior_positive(self):
        assert self.results is not None
        assert self.results['kl_to_prior'] > 0, (
            f"KL to prior should be positive, got {self.results['kl_to_prior']}"
        )

    def test_posterior_var_positive(self):
        assert self.results is not None
        assert self.results['posterior_var'] > 0

    def test_values_finite(self):
        assert self.results is not None
        for key in ['posterior_var', 'kl_to_prior', 'kl_reduction_loss',
                     'nll_at_test_point', 'logprob_at_test_point']:
            v = self.results[key]
            assert math.isfinite(v), f"{key} is not finite: {v}"
        for v in self.results['posterior_mean']:
            assert math.isfinite(v), f"posterior_mean element is not finite: {v}"


# ============================================================
# Cross-function consistency
# ============================================================

class TestCrossConsistency:

    def test_nll_logprob_relation(self):
        """gm_nll_loss(gm, x) + gm_logprob(gm, x.unsqueeze(1))[:, 0]
        must equal -D/2 * log(2*pi) for any GM and sample."""
        torch.manual_seed(99)
        D = 4
        means = torch.randn(3, 5, D)
        logstds = torch.randn(3, 1, 1) * 0.5
        logweights = torch.randn(3, 5, 1)
        sample = torch.randn(3, D)

        gm = {'means': means, 'logstds': logstds, 'logweights': logweights}
        nll = gm_nll_loss(gm, sample)
        lp = gm_logprob(gm, sample.unsqueeze(1))[:, 0]

        expected_sum = -0.5 * D * math.log(2 * math.pi)
        torch.testing.assert_close(
            nll + lp,
            torch.full_like(nll, expected_sum),
            atol=1e-4, rtol=1e-4,
        )
