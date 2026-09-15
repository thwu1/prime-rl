"""
Tests for Gaussian Mixture operations library.

"""

import ctypes
import math
import os
import sys

import numpy as np
import pytest
import torch

sys.path.insert(0, "/app")
from gm_ops import (
    gm_kl_div,
    gm_logprob,
    gm_logpdf_c,
    gm_mul_iso_gaussian,
    gm_nll_loss,
    gm_to_iso_gaussian,
    gm_to_mean,
    gm_to_sample,
)


# ===================================================================
# gm_nll_loss
# ===================================================================

class TestGMNLLLoss:
    """Tests for the Gaussian Mixture NLL loss function."""

    def test_single_gaussian_at_mean(self):
        """NLL of a single Gaussian evaluated at its mean (logstd=0)."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        sample = torch.tensor([[0.0, 0.0]])
        nll = gm_nll_loss(gm, sample)
        torch.testing.assert_close(nll, torch.tensor([0.0]), atol=1e-6, rtol=1e-5)

    def test_two_component_known_value(self):
        """Two-component GM with equal logweights, sample at component 0."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [1.0, 1.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        sample = torch.tensor([[0.0, 0.0]])
        nll = gm_nll_loss(gm, sample)
        # gaussian_ll = [0, -1]; logsumexp([0,-1]) = log(1+e^{-1})
        expected = -math.log(1.0 + math.exp(-1.0))
        torch.testing.assert_close(nll, torch.tensor([expected]), atol=1e-4, rtol=1e-4)

    def test_nonzero_logstd(self):
        """NLL with sigma = 2 (logstd = log 2)."""
        log2 = math.log(2.0)
        gm = {
            "means": torch.tensor([[[0.0, 0.0]]]),
            "logstds": torch.tensor([[[log2]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        sample = torch.tensor([[2.0, 0.0]])
        nll = gm_nll_loss(gm, sample)
        expected = 0.5 + 2.0 * log2
        torch.testing.assert_close(nll, torch.tensor([expected]), atol=1e-4, rtol=1e-4)

    def test_batch_at_means(self):
        """Batch of 2 single-Gaussian GMs, each sample at its own mean."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0]], [[3.0, -1.0]]]),
            "logstds": torch.tensor([[[0.0]], [[0.0]]]),
            "logweights": torch.tensor([[[0.0]], [[0.0]]]),
        }
        sample = torch.tensor([[0.0, 0.0], [3.0, -1.0]])
        nll = gm_nll_loss(gm, sample)
        torch.testing.assert_close(nll, torch.tensor([0.0, 0.0]), atol=1e-6, rtol=1e-5)

    def test_output_shape(self):
        """Output has shape (bs,)."""
        bs, K, D = 3, 4, 5
        gm = {
            "means": torch.randn(bs, K, D),
            "logstds": torch.zeros(bs, 1, 1),
            "logweights": torch.zeros(bs, K, 1),
        }
        sample = torch.randn(bs, D)
        nll = gm_nll_loss(gm, sample)
        assert nll.shape == (bs,), f"Expected ({bs},), got {nll.shape}"

    def test_gradient_flows(self):
        """Gradients w.r.t. means and logstds are finite."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [1.0, 1.0]]], requires_grad=True),
            "logstds": torch.tensor([[[0.0]]], requires_grad=True),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        sample = torch.tensor([[0.5, 0.5]])
        nll = gm_nll_loss(gm, sample)
        nll.sum().backward()
        assert gm["means"].grad is not None
        assert gm["logstds"].grad is not None
        assert not torch.isnan(gm["means"].grad).any()
        assert not torch.isnan(gm["logstds"].grad).any()

    def test_many_components(self):
        """Verify against a direct computation with K=8, D=4."""
        torch.manual_seed(123)
        K, D = 8, 4
        gm = {
            "means": torch.randn(1, K, D),
            "logstds": torch.tensor([[[0.3]]]),
            "logweights": torch.randn(1, K, 1),
        }
        sample = torch.randn(1, D)

        # Reference: manual computation
        inv_s = torch.exp(-gm["logstds"]).clamp(max=1e4)
        dw = (sample.unsqueeze(1) - gm["means"]) * inv_s
        gll = (-0.5 * dw.square() - gm["logstds"]).sum(dim=-1)
        ref = -torch.logsumexp(gll + gm["logweights"].squeeze(-1), dim=-1)

        nll = gm_nll_loss(gm, sample)
        torch.testing.assert_close(nll, ref, atol=1e-5, rtol=1e-5)

    def test_three_dimensions(self):
        """NLL with D=3, verifying dimension handling."""
        gm = {
            "means": torch.tensor([[[1.0, 0.0, -1.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        sample = torch.tensor([[0.0, 0.0, 0.0]])
        nll = gm_nll_loss(gm, sample)
        torch.testing.assert_close(nll, torch.tensor([1.0]), atol=1e-5, rtol=1e-5)


# ===================================================================
# gm_to_iso_gaussian
# ===================================================================

class TestGMToIsoGaussian:
    """Tests for moment-matching GM -> isotropic Gaussian."""

    def test_single_component(self):
        """K=1: recovered Gaussian should match the single component."""
        gm = {
            "means": torch.tensor([[[1.0, 2.0]]]),
            "logstds": torch.tensor([[[0.5]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        result = gm_to_iso_gaussian(gm)
        torch.testing.assert_close(result["mean"], torch.tensor([[1.0, 2.0]]), atol=1e-5, rtol=1e-5)
        torch.testing.assert_close(result["var"], torch.tensor([[math.exp(1.0)]]), atol=1e-5, rtol=1e-5)

    def test_symmetric_components(self):
        """Two equal-weight components placed symmetrically around the origin."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [4.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        result = gm_to_iso_gaussian(gm)
        torch.testing.assert_close(result["mean"], torch.tensor([[2.0, 0.0]]), atol=1e-5, rtol=1e-5)
        torch.testing.assert_close(result["var"], torch.tensor([[3.0]]), atol=1e-5, rtol=1e-5)

    def test_unequal_weights(self):
        """Weights [0.25, 0.75] via logweights [0, log(3)]."""
        log3 = math.log(3.0)
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [4.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [log3]]]),
        }
        result = gm_to_iso_gaussian(gm)
        torch.testing.assert_close(result["mean"], torch.tensor([[3.0, 0.0]]), atol=1e-4, rtol=1e-4)
        torch.testing.assert_close(result["var"], torch.tensor([[2.5]]), atol=1e-4, rtol=1e-4)

    def test_output_shapes(self):
        bs, K, D = 2, 5, 3
        gm = {
            "means": torch.randn(bs, K, D),
            "logstds": torch.zeros(bs, 1, 1),
            "logweights": torch.zeros(bs, K, 1),
        }
        result = gm_to_iso_gaussian(gm)
        assert result["mean"].shape == (bs, D)
        assert result["var"].shape == (bs, 1)

    def test_higher_dimensional(self):
        """D=4, two components on diagonal, checking isotropic variance."""
        gm = {
            "means": torch.tensor([[[1.0, 1.0, 1.0, 1.0], [-1.0, -1.0, -1.0, -1.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        result = gm_to_iso_gaussian(gm)
        torch.testing.assert_close(result["mean"], torch.zeros(1, 4), atol=1e-5, rtol=1e-5)
        torch.testing.assert_close(result["var"], torch.tensor([[2.0]]), atol=1e-5, rtol=1e-5)


# ===================================================================
# gm_mul_iso_gaussian
# ===================================================================

class TestGMMulIsoGaussian:
    """Tests for the GM x isotropic-Gaussian product."""

    def test_known_update(self):
        """Pre-computed result for equal-power multiplication."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [2.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        gaussian = {"mean": torch.tensor([[1.0, 0.0]]), "var": torch.tensor([[1.0]])}

        new_gm, power = gm_mul_iso_gaussian(gm, gaussian, 1.0, 1.0)

        torch.testing.assert_close(
            new_gm["means"],
            torch.tensor([[[0.5, 0.0], [1.5, 0.0]]]),
            atol=1e-4, rtol=1e-4,
        )
        torch.testing.assert_close(
            new_gm["logstds"],
            torch.tensor([[[-0.5 * math.log(2.0)]]]),
            atol=1e-4, rtol=1e-4,
        )
        torch.testing.assert_close(
            new_gm["logweights"],
            torch.tensor([[[-math.log(2.0)], [-math.log(2.0)]]]),
            atol=1e-4, rtol=1e-4,
        )
        assert power == 1.0

    def test_closer_component_upweighted(self):
        """Component closer to the Gaussian mean gets higher weight."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [4.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        gaussian = {"mean": torch.tensor([[0.0, 0.0]]), "var": torch.tensor([[1.0]])}

        new_gm, _ = gm_mul_iso_gaussian(gm, gaussian, 1.0, 1.0)
        weights = new_gm["logweights"].squeeze(-1).softmax(dim=-1)
        assert weights[0, 0] > weights[0, 1], \
            "Component closer to Gaussian mean should have higher weight"

    def test_wide_gaussian_preserves_means(self):
        """Very wide Gaussian (var=1e6) barely changes the GM."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [1.0, 1.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        gaussian = {"mean": torch.tensor([[0.5, 0.5]]), "var": torch.tensor([[1e6]])}

        new_gm, _ = gm_mul_iso_gaussian(gm, gaussian, 1.0, 1.0)
        torch.testing.assert_close(new_gm["means"], gm["means"], atol=1e-2, rtol=1e-2)

    def test_output_shapes(self):
        bs, K, D = 2, 3, 4
        gm = {
            "means": torch.randn(bs, K, D),
            "logstds": torch.zeros(bs, 1, 1),
            "logweights": torch.zeros(bs, K, 1),
        }
        gaussian = {"mean": torch.randn(bs, D), "var": torch.ones(bs, 1)}
        new_gm, _ = gm_mul_iso_gaussian(gm, gaussian, 1.0, 1.0)
        assert new_gm["means"].shape == (bs, K, D)
        assert new_gm["logstds"].shape == (bs, 1, 1)
        assert new_gm["logweights"].shape == (bs, K, 1)

    def test_power_scaling(self):
        """Higher Gaussian power pulls means further toward Gaussian mean."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [4.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        gaussian = {"mean": torch.tensor([[2.0, 0.0]]), "var": torch.tensor([[1.0]])}

        new_gm_low, _ = gm_mul_iso_gaussian(gm, gaussian, 1.0, 0.5)
        new_gm_high, _ = gm_mul_iso_gaussian(gm, gaussian, 1.0, 2.0)

        dist_low = (new_gm_low["means"] - gaussian["mean"].unsqueeze(1)).norm(dim=-1).mean()
        dist_high = (new_gm_high["means"] - gaussian["mean"].unsqueeze(1)).norm(dim=-1).mean()
        assert dist_high < dist_low, "Higher power should pull means closer"

    def test_asymmetric_powers_known_value(self):
        """Verify exact output with gm_power=1, gaussian_power=2."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        gaussian = {"mean": torch.tensor([[3.0, 0.0]]), "var": torch.tensor([[1.0]])}

        new_gm, _ = gm_mul_iso_gaussian(gm, gaussian, 1.0, 2.0)

        torch.testing.assert_close(
            new_gm["means"],
            torch.tensor([[[2.0, 0.0]]]),
            atol=1e-4, rtol=1e-4,
        )


# ===================================================================
# gm_logprob
# ===================================================================

class TestGMLogprob:
    """Tests for the full GM log-probability."""

    def test_single_gaussian_at_mean(self):
        """log N(0; 0, I) = -D/2 * log(2*pi)."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        samples = torch.tensor([[[0.0, 0.0]]])
        logprob, gauss_lp = gm_logprob(gm, samples)

        expected = -math.log(2.0 * math.pi)
        torch.testing.assert_close(logprob, torch.tensor([[expected]]), atol=1e-4, rtol=1e-4)
        torch.testing.assert_close(gauss_lp, torch.tensor([[[expected]]]), atol=1e-4, rtol=1e-4)

    def test_multiple_samples(self):
        """Three samples from a single-Gaussian GM."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        samples = torch.tensor([[[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]])

        logprob, _ = gm_logprob(gm, samples)
        c = -math.log(2.0 * math.pi)
        expected = torch.tensor([[c, c - 0.5, c - 0.5]])
        torch.testing.assert_close(logprob, expected, atol=1e-4, rtol=1e-4)

    def test_unequal_weights(self):
        """logprob with non-uniform component weights must reflect mixing."""
        log3 = math.log(3.0)
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [0.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[log3], [0.0]]]),
        }
        samples = torch.tensor([[[0.0, 0.0]]])
        logprob, _ = gm_logprob(gm, samples)

        c = -math.log(2.0 * math.pi)
        expected = c + math.log(4.0)
        torch.testing.assert_close(logprob, torch.tensor([[expected]]), atol=1e-4, rtol=1e-4)

    def test_consistency_with_nll(self):
        """logprob = -nll - D/2*log(2*pi) for the same inputs."""
        D = 3
        gm = {
            "means": torch.tensor([[[1.0, 2.0, 3.0], [0.0, -1.0, 2.0]]]),
            "logstds": torch.tensor([[[0.5]]]),
            "logweights": torch.tensor([[[0.3], [-0.2]]]),
        }
        sample = torch.tensor([[0.5, 1.0, 2.5]])

        nll = gm_nll_loss(gm, sample)
        logprob = gm_logprob(gm, sample.unsqueeze(1))[0].squeeze(1)

        expected_logprob = -nll - D / 2.0 * math.log(2.0 * math.pi)
        torch.testing.assert_close(logprob, expected_logprob, atol=1e-4, rtol=1e-4)

    def test_output_shapes(self):
        bs, K, D, N = 2, 3, 4, 5
        gm = {
            "means": torch.randn(bs, K, D),
            "logstds": torch.zeros(bs, 1, 1),
            "logweights": torch.zeros(bs, K, 1),
        }
        samples = torch.randn(bs, N, D)
        logprob, gauss_lp = gm_logprob(gm, samples)
        assert logprob.shape == (bs, N), f"Expected ({bs}, {N}), got {logprob.shape}"
        assert gauss_lp.shape == (bs, N, K), f"Expected ({bs}, {N}, {K}), got {gauss_lp.shape}"

    def test_gradient_flows(self):
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [1.0, 1.0]]], requires_grad=True),
            "logstds": torch.tensor([[[0.0]]], requires_grad=True),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        samples = torch.tensor([[[0.5, 0.5]]])
        logprob, _ = gm_logprob(gm, samples)
        logprob.sum().backward()
        assert gm["means"].grad is not None
        assert not torch.isnan(gm["means"].grad).any()

    def test_high_dimensional(self):
        """D=8, two components, sample at origin."""
        D = 8
        gm = {
            "means": torch.tensor([[[0.0] * D, [1.0] * D]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        samples = torch.zeros(1, 1, D)
        logprob, _ = gm_logprob(gm, samples)

        c = -D / 2.0 * math.log(2.0 * math.pi)
        expected = math.log(math.exp(c) + math.exp(c - D / 2.0))
        torch.testing.assert_close(logprob, torch.tensor([[expected]]), atol=1e-3, rtol=1e-3)

    def test_weighted_two_component(self):
        """Two components with different weights and separated means."""
        log2 = math.log(2.0)
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [5.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[log2], [0.0]]]),
        }
        samples = torch.tensor([[[0.0, 0.0]]])
        logprob, _ = gm_logprob(gm, samples)

        c = -math.log(2.0 * math.pi)
        expected = math.log(math.exp(log2 + c) + math.exp(c - 12.5))
        torch.testing.assert_close(logprob, torch.tensor([[expected]]), atol=1e-4, rtol=1e-4)


# ===================================================================
# gm_kl_div
# ===================================================================

class TestGMKLDiv:
    """Tests for Monte Carlo KL divergence estimation."""

    def test_self_kl_is_zero(self):
        """KL(p || p) = 0 exactly (same function on both sides)."""
        torch.manual_seed(42)
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [2.0, 1.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        kl = gm_kl_div(gm, gm, n_samples=500)
        torch.testing.assert_close(kl, torch.tensor([0.0]), atol=1e-5, rtol=1e-5)

    def test_nonnegative(self):
        """KL(p || q) >= 0 for distinct distributions."""
        torch.manual_seed(42)
        gm_p = {
            "means": torch.tensor([[[0.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        gm_q = {
            "means": torch.tensor([[[2.0, 0.0]]]),
            "logstds": torch.tensor([[[0.5]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        kl = gm_kl_div(gm_p, gm_q, n_samples=5000)
        assert kl.item() > -0.05, f"KL should be non-negative, got {kl.item():.4f}"

    def test_analytical_gaussian_kl(self):
        """For K=1 (pure Gaussians), compare to the closed-form KL."""
        torch.manual_seed(42)
        D = 2
        sigma_p, sigma_q = 1.0, 2.0
        mu_q = torch.tensor([[0.5, 0.0]])

        gm_p = {
            "means": torch.tensor([[[0.0, 0.0]]]),
            "logstds": torch.tensor([[[math.log(sigma_p)]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        gm_q = {
            "means": mu_q.unsqueeze(1),
            "logstds": torch.tensor([[[math.log(sigma_q)]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }

        kl_mc = gm_kl_div(gm_p, gm_q, n_samples=10000)

        kl_true = (
            D / 2.0 * (sigma_p**2 / sigma_q**2 - 1.0 + math.log(sigma_q**2 / sigma_p**2))
            + mu_q.square().sum().item() / (2.0 * sigma_q**2)
        )

        assert abs(kl_mc.item() - kl_true) < 0.15, (
            f"MC KL ({kl_mc.item():.4f}) far from analytical ({kl_true:.4f})"
        )

    def test_output_shape(self):
        torch.manual_seed(42)
        bs = 2
        gm_p = {
            "means": torch.randn(bs, 3, 4),
            "logstds": torch.zeros(bs, 1, 1),
            "logweights": torch.zeros(bs, 3, 1),
        }
        gm_q = {
            "means": torch.randn(bs, 2, 4),
            "logstds": torch.zeros(bs, 1, 1),
            "logweights": torch.zeros(bs, 2, 1),
        }
        kl = gm_kl_div(gm_p, gm_q, n_samples=100)
        assert kl.shape == (bs,), f"Expected ({bs},), got {kl.shape}"

    def test_asymmetry(self):
        """KL(p||q) != KL(q||p) in general."""
        torch.manual_seed(42)
        gm_p = {
            "means": torch.tensor([[[0.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        gm_q = {
            "means": torch.tensor([[[2.0, 0.0]]]),
            "logstds": torch.tensor([[[0.5]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        torch.manual_seed(42)
        kl_pq = gm_kl_div(gm_p, gm_q, n_samples=5000)
        torch.manual_seed(42)
        kl_qp = gm_kl_div(gm_q, gm_p, n_samples=5000)
        assert abs(kl_pq.item() - kl_qp.item()) > 0.01, (
            "KL should be asymmetric for these distributions"
        )

    def test_scale_invariance(self):
        """KL estimate should not change drastically with more samples."""
        torch.manual_seed(42)
        gm_p = {
            "means": torch.tensor([[[0.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        gm_q = {
            "means": torch.tensor([[[1.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0]]]),
        }
        torch.manual_seed(42)
        kl_100 = gm_kl_div(gm_p, gm_q, n_samples=100)
        torch.manual_seed(42)
        kl_1000 = gm_kl_div(gm_p, gm_q, n_samples=1000)
        assert abs(kl_100.item() - kl_1000.item()) < 0.5, (
            f"KL should be roughly consistent: {kl_100.item():.3f} vs {kl_1000.item():.3f}"
        )


# ===================================================================
# C Extension — gm_logpdf_c
# ===================================================================

class TestCExtension:
    """Tests for the compiled C extension batch log-PDF."""

    def test_shared_library_exists(self):
        """The compiled shared library must exist at /app/libgm_logpdf.so."""
        assert os.path.exists("/app/libgm_logpdf.so"), (
            "libgm_logpdf.so not found at /app/. "
            "Compile gm_logpdf.c with: gcc -shared -fPIC -O2 -o libgm_logpdf.so gm_logpdf.c -lm"
        )

    def test_single_gaussian_at_mean(self):
        """Single component at origin, sample at origin."""
        means = np.array([[0.0, 0.0]], dtype=np.float64)
        logweights = np.array([0.0], dtype=np.float64)
        samples = np.array([[0.0, 0.0]], dtype=np.float64)

        result = gm_logpdf_c(means, 0.0, logweights, samples)

        expected = -math.log(2.0 * math.pi)
        np.testing.assert_allclose(result, [expected], atol=1e-10, rtol=1e-10)

    def test_displaced_sample(self):
        """Single Gaussian, sample displaced by 1 in each dimension."""
        D = 3
        means = np.zeros((1, D), dtype=np.float64)
        logweights = np.array([0.0], dtype=np.float64)
        samples = np.ones((1, D), dtype=np.float64)

        result = gm_logpdf_c(means, 0.0, logweights, samples)

        # -0.5 * 3 - 0 + (-3/2 * log(2pi)) = -1.5 - 1.5*log(2pi)
        expected = -0.5 * D - D / 2.0 * math.log(2.0 * math.pi)
        np.testing.assert_allclose(result, [expected], atol=1e-10, rtol=1e-10)

    def test_two_component_mixture(self):
        """Two-component mixture with known analytical value."""
        means = np.array([[0.0, 0.0], [5.0, 0.0]], dtype=np.float64)
        log2 = math.log(2.0)
        logweights = np.array([log2, 0.0], dtype=np.float64)
        samples = np.array([[0.0, 0.0]], dtype=np.float64)

        result = gm_logpdf_c(means, 0.0, logweights, samples)

        # With unnormalized logweights:
        # output = logsumexp([log2 + c, 0 + (c - 12.5)])
        #        = log(exp(log2 + c) + exp(c - 12.5))
        c = -math.log(2.0 * math.pi)
        expected = math.log(math.exp(log2 + c) + math.exp(c - 12.5))
        np.testing.assert_allclose(result, [expected], atol=1e-8, rtol=1e-8)

    def test_matches_python_logprob(self):
        """C extension output should match Python gm_logprob for random inputs."""
        torch.manual_seed(42)
        np.random.seed(42)
        K, D = 4, 3
        gm = {
            "means": torch.randn(1, K, D),
            "logstds": torch.tensor([[[0.5]]]),
            "logweights": torch.randn(1, K, 1),
        }
        samples_t = torch.randn(1, 10, D)

        py_logprob = gm_logprob(gm, samples_t)[0]

        c_logprob = gm_logpdf_c(
            gm["means"][0].numpy().astype(np.float64),
            gm["logstds"][0, 0, 0].item(),
            gm["logweights"][0, :, 0].numpy().astype(np.float64),
            samples_t[0].numpy().astype(np.float64),
        )

        np.testing.assert_allclose(
            c_logprob,
            py_logprob[0].detach().numpy(),
            atol=1e-5, rtol=1e-5,
        )

    def test_high_dimensional(self):
        """D=8 stress test for the C extension."""
        D = 8
        K = 3
        means = np.random.RandomState(123).randn(K, D)
        logweights = np.array([0.0, 1.0, -0.5], dtype=np.float64)
        samples = np.random.RandomState(456).randn(20, D)

        result = gm_logpdf_c(means, 0.3, logweights, samples)

        assert result.shape == (20,), f"Expected (20,), got {result.shape}"
        assert np.all(np.isfinite(result)), "All log-probabilities should be finite"
        assert np.all(result < 0), "Log-probabilities should be negative for D=8"


# ===================================================================
# Integration tests
# ===================================================================

class TestIntegration:
    """Tests composing multiple GM operations together."""

    def test_nll_logprob_consistency(self):
        """logprob and nll should differ only by the Gaussian constant."""
        D = 3
        gm = {
            "means": torch.tensor([[[1.0, 2.0, 3.0], [0.0, -1.0, 2.0]]]),
            "logstds": torch.tensor([[[0.5]]]),
            "logweights": torch.tensor([[[0.3], [-0.2]]]),
        }
        sample = torch.tensor([[0.5, 1.0, 2.5]])

        nll = gm_nll_loss(gm, sample)
        logprob = gm_logprob(gm, sample.unsqueeze(1))[0].squeeze(1)

        const = D / 2.0 * math.log(2.0 * math.pi)
        residual = logprob + nll + const
        torch.testing.assert_close(residual, torch.zeros(1), atol=1e-4, rtol=1e-4)

    def test_posterior_convergence(self):
        """Strong Gaussian power should pull means toward Gaussian mean."""
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [4.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        iso = gm_to_iso_gaussian(gm)
        updated_gm, _ = gm_mul_iso_gaussian(gm, iso, 1.0, 10.0)

        dist = (updated_gm["means"] - iso["mean"].unsqueeze(1)).norm(dim=-1).max()
        assert dist.item() < 0.5, f"Means should converge, max_dist={dist.item():.4f}"

    def test_sample_logprob_finite(self):
        """Samples from GM should have finite logprob under the same GM."""
        torch.manual_seed(42)
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [3.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        samples = gm_to_sample(gm, 100)
        logprob = gm_logprob(gm, samples)[0]
        assert logprob.shape == (1, 100)
        assert not torch.isnan(logprob).any()
        assert not torch.isinf(logprob).any()

    def test_kl_of_iso_approximation(self):
        """KL from a GM to its isotropic approximation should be non-negative and finite."""
        torch.manual_seed(42)
        gm = {
            "means": torch.tensor([[[0.0, 0.0], [3.0, 0.0]]]),
            "logstds": torch.tensor([[[0.0]]]),
            "logweights": torch.tensor([[[0.0], [0.0]]]),
        }
        iso = gm_to_iso_gaussian(gm)
        iso_gm = {
            "means": iso["mean"].unsqueeze(1),
            "logstds": (0.5 * torch.log(iso["var"])).unsqueeze(-1),
            "logweights": torch.zeros(1, 1, 1),
        }
        kl = gm_kl_div(gm, iso_gm, n_samples=5000)
        assert kl.item() > -0.1, f"KL should be non-negative, got {kl.item():.4f}"
        assert kl.item() < 10.0, f"KL should be finite, got {kl.item():.4f}"
