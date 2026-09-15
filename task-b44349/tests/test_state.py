"""
Tests for Score Engine — verifies gm_score, gm_score_divergence,
and gm_kernel_stein_discrepancy against analytical references,
finite-difference checks, and mathematical identities.

"""
import sys
sys.path.insert(0, '/app')

import math
import torch
import pytest
from score_engine import gm_score, gm_score_divergence, gm_kernel_stein_discrepancy
from gm_ops import gm_log_prob


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_gm(means, logstd, logweights):
    """Create a GM dict from raw values."""
    m = torch.tensor(means, dtype=torch.float64)
    if m.dim() == 2:
        m = m.unsqueeze(0)
    ls = torch.tensor([[[logstd]]], dtype=torch.float64)
    lw = torch.tensor(logweights, dtype=torch.float64)
    if lw.dim() == 1:
        lw = lw.unsqueeze(0)
    return {'means': m, 'logstds': ls, 'logweights': lw}


def _expand_gm(gm, n):
    """Expand a B=1 GM to B=n for batched score evaluation."""
    return {
        'means': gm['means'].expand(n, -1, -1),
        'logstds': gm['logstds'].expand(n, -1, -1),
        'logweights': gm['logweights'].expand(n, -1),
    }


def _fd_score(gm, x, eps=1e-5):
    """Finite-difference approximation of score using gm_log_prob."""
    D = x.shape[-1]
    fd = torch.zeros_like(x)
    for d in range(D):
        x_p = x.clone()
        x_m = x.clone()
        x_p[0, d] += eps
        x_m[0, d] -= eps
        lp_p = gm_log_prob(gm, x_p.unsqueeze(1)).squeeze()
        lp_m = gm_log_prob(gm, x_m.unsqueeze(1)).squeeze()
        fd[0, d] = (lp_p - lp_m) / (2 * eps)
    return fd


def _sample_gm_direct(means_list, logstd, n_per_component, dtype=torch.float64):
    """Sample from a GM by generating n_per_component samples from each component.

    Returns (total_N, D) tensor for equal-weight mixtures.
    """
    sigma = math.exp(logstd)
    parts = []
    for mu_vals in means_list:
        mu = torch.tensor(mu_vals, dtype=dtype)
        D = mu.shape[0]
        part = mu + sigma * torch.randn(n_per_component, D, dtype=dtype)
        parts.append(part)
    return torch.cat(parts, dim=0)


# ===================================================================
# 1. gm_score — numerically stable score function
# ===================================================================
class TestGMScore:
    def test_single_gaussian_at_mean(self):
        """Score of N(0,I) at origin should be zero."""
        gm = _make_gm([[0.0, 0.0]], 0.0, [0.0])
        x = torch.tensor([[0.0, 0.0]], dtype=torch.float64)
        s = gm_score(gm, x)
        torch.testing.assert_close(
            s, torch.zeros(1, 2, dtype=torch.float64), atol=1e-6, rtol=1e-6)

    def test_single_gaussian_offset(self):
        """Score of N(0,I) at (1,0) should be (-1,0)."""
        gm = _make_gm([[0.0, 0.0]], 0.0, [0.0])
        x = torch.tensor([[1.0, 0.0]], dtype=torch.float64)
        s = gm_score(gm, x)
        torch.testing.assert_close(
            s, torch.tensor([[-1.0, 0.0]], dtype=torch.float64), atol=1e-6, rtol=1e-6)

    def test_finite_differences_near_modes(self):
        """Score should match finite-difference approximation near component means."""
        gm = _make_gm([[-1.0, 0.5], [1.0, -0.5]], 0.3, [0.2, -0.3])
        x = torch.tensor([[0.3, 0.7]], dtype=torch.float64)
        s = gm_score(gm, x)
        fd = _fd_score(gm, x)
        torch.testing.assert_close(s, fd, atol=1e-4, rtol=1e-4)

    def test_tail_stability_no_nan(self):
        """Score must be finite when x is far from all components."""
        gm = _make_gm([[0.0, 0.0], [1.0, 1.0]], 0.0, [0.0, 0.0])
        x = torch.tensor([[50.0, 50.0]], dtype=torch.float64)
        s = gm_score(gm, x)
        assert torch.isfinite(s).all(), f"Score is non-finite in tails: {s}"
        # Score should point toward the nearest component (1,1)
        assert s[0, 0].item() < 0, "x-score should be negative (toward component)"
        assert s[0, 1].item() < 0, "y-score should be negative (toward component)"

    def test_tail_finite_differences(self):
        """Score in tails should still match finite differences of log p."""
        gm = _make_gm([[0.0, 0.0]], 0.0, [0.0])
        x = torch.tensor([[30.0, 0.0]], dtype=torch.float64)
        s = gm_score(gm, x)
        assert torch.isfinite(s).all(), f"Score not finite at x=30: {s}"
        fd = _fd_score(gm, x)
        torch.testing.assert_close(s, fd, atol=1e-3, rtol=1e-3)

    def test_small_variance_stability(self):
        """Score must be finite for very small sigma."""
        gm = _make_gm([[0.0, 0.0]], -8.0, [0.0])  # sigma ~ 3e-4
        x = torch.tensor([[1e-3, 0.0]], dtype=torch.float64)
        s = gm_score(gm, x)
        assert torch.isfinite(s).all(), f"Score not finite for small sigma: {s}"
        # x > mu in dim 0, score should be negative
        assert s[0, 0].item() < 0

    def test_degenerate_weights(self):
        """When one component has overwhelming weight, score ~ that component's score."""
        gm = _make_gm([[0.0, 0.0], [3.0, 3.0]], 0.0, [100.0, 0.0])
        x = torch.tensor([[0.5, 0.5]], dtype=torch.float64)
        s = gm_score(gm, x)
        expected = torch.tensor([[-0.5, -0.5]], dtype=torch.float64)
        torch.testing.assert_close(s, expected, atol=1e-3, rtol=1e-3)

    def test_batch_dimension(self):
        """Score with B=2 should return shape (2, D)."""
        gm = {
            'means': torch.tensor([[[0.0, 0.0]], [[1.0, 1.0]]], dtype=torch.float64),
            'logstds': torch.tensor([[[0.0]], [[0.0]]], dtype=torch.float64),
            'logweights': torch.tensor([[0.0], [0.0]], dtype=torch.float64),
        }
        x = torch.tensor([[0.0, 0.0], [1.0, 1.0]], dtype=torch.float64)
        s = gm_score(gm, x)
        assert s.shape == (2, 2), f"Expected (2,2), got {s.shape}"
        # At mean, score should be 0
        torch.testing.assert_close(
            s, torch.zeros(2, 2, dtype=torch.float64), atol=1e-6, rtol=1e-6)

    def test_three_component_fd(self):
        """Score with K=3 components should match finite differences."""
        gm = _make_gm([[0.0, 0.0], [2.0, -1.0], [-1.0, 3.0]], -0.2, [0.5, 0.1, -0.3])
        x = torch.tensor([[0.5, 1.0]], dtype=torch.float64)
        s = gm_score(gm, x)
        fd = _fd_score(gm, x)
        torch.testing.assert_close(s, fd, atol=1e-4, rtol=1e-4)


# ===================================================================
# 2. gm_score_divergence — Laplacian of log p
# ===================================================================
class TestGMScoreDivergence:
    def test_single_gaussian_unit_var(self):
        """For N(0, I) in D=2: div(score) = -D/sigma^2 = -2, regardless of x."""
        gm = _make_gm([[0.0, 0.0]], 0.0, [0.0])
        x = torch.tensor([[0.5, -0.3]], dtype=torch.float64)
        div_s = gm_score_divergence(gm, x)
        torch.testing.assert_close(
            div_s, torch.tensor([-2.0], dtype=torch.float64), atol=1e-4, rtol=1e-4)

    def test_single_gaussian_nonunit_var(self):
        """For N(0, sigma^2 I) with sigma^2=e, D=2: div(score) = -2/e."""
        logstd = 0.5
        gm = _make_gm([[0.0, 0.0]], logstd, [0.0])
        x = torch.tensor([[0.1, 0.2]], dtype=torch.float64)
        div_s = gm_score_divergence(gm, x)
        expected = -2.0 / math.exp(2 * logstd)
        torch.testing.assert_close(
            div_s, torch.tensor([expected], dtype=torch.float64), atol=1e-4, rtol=1e-4)

    def test_single_gaussian_constant_over_x(self):
        """For a single Gaussian, div(score) should be the same everywhere."""
        gm = _make_gm([[1.0, -2.0]], 0.5, [0.0])
        x1 = torch.tensor([[0.0, 0.0]], dtype=torch.float64)
        x2 = torch.tensor([[5.0, -3.0]], dtype=torch.float64)
        d1 = gm_score_divergence(gm, x1)
        d2 = gm_score_divergence(gm, x2)
        torch.testing.assert_close(d1, d2, atol=1e-6, rtol=1e-6)

    def test_finite_differences_of_score(self):
        """div(score) should match FD of score components: sum_d ds_d/dx_d."""
        gm = _make_gm([[-1.0, 0.5], [1.0, -0.5]], 0.3, [0.2, -0.3])
        x = torch.tensor([[0.3, 0.7]], dtype=torch.float64)
        div_s = gm_score_divergence(gm, x)

        eps = 1e-5
        fd_div = torch.tensor([0.0], dtype=torch.float64)
        for d in range(2):
            x_p = x.clone()
            x_m = x.clone()
            x_p[0, d] += eps
            x_m[0, d] -= eps
            s_p = gm_score(gm, x_p)
            s_m = gm_score(gm, x_m)
            fd_div += (s_p[0, d] - s_m[0, d]) / (2 * eps)

        torch.testing.assert_close(div_s, fd_div, atol=1e-3, rtol=1e-3)

    def test_mixture_between_modes(self):
        """Divergence at the midpoint between two equal-weight modes with sigma=1, D=2.

        At x=0 for GM with means [-1,0],[1,0]:
        r_1 = r_2 = 0.5
        s_1 = [1, 0], s_2 = [-1, 0]
        score = [0, 0]
        E[||s||^2] = 0.5*(1) + 0.5*(1) = 1
        div = 1 - 0 - 2 = -1
        """
        gm = _make_gm([[-1.0, 0.0], [1.0, 0.0]], 0.0, [0.0, 0.0])
        x = torch.tensor([[0.0, 0.0]], dtype=torch.float64)
        div_s = gm_score_divergence(gm, x)
        torch.testing.assert_close(
            div_s, torch.tensor([-1.0], dtype=torch.float64), atol=1e-4, rtol=1e-4)

    def test_stein_identity_single_gaussian(self):
        """E_p[div(s) + ||s||^2] = 0 for a single Gaussian (exact result)."""
        torch.manual_seed(42)
        gm = _make_gm([[1.0, -1.0]], 0.3, [0.0])
        sigma = math.exp(0.3)
        mu = torch.tensor([1.0, -1.0], dtype=torch.float64)
        samples = mu + sigma * torch.randn(8000, 2, dtype=torch.float64)
        N = samples.shape[0]
        gm_exp = _expand_gm(gm, N)

        s = gm_score(gm_exp, samples)
        div_s = gm_score_divergence(gm_exp, samples)
        stein = (div_s + (s ** 2).sum(dim=-1)).mean().item()
        assert abs(stein) < 0.1, f"Stein identity violated: {stein}"

    def test_stein_identity_mixture(self):
        """E_p[div(s) + ||s||^2] = 0 for a two-component GM."""
        torch.manual_seed(42)
        gm = _make_gm([[-2.0, 0.0], [2.0, 0.0]], 0.3, [0.0, 0.0])
        # Direct sampling: 50/50 split from each component
        samples = _sample_gm_direct(
            [[-2.0, 0.0], [2.0, 0.0]], logstd=0.3, n_per_component=4000)
        N = samples.shape[0]
        gm_exp = _expand_gm(gm, N)

        s = gm_score(gm_exp, samples)
        div_s = gm_score_divergence(gm_exp, samples)
        stein = (div_s + (s ** 2).sum(dim=-1)).mean().item()
        assert abs(stein) < 0.2, f"Stein identity violated for mixture: {stein}"

    def test_tail_stability(self):
        """Divergence must be finite in the tails."""
        gm = _make_gm([[0.0, 0.0]], 0.0, [0.0])
        x = torch.tensor([[30.0, 0.0]], dtype=torch.float64)
        div_s = gm_score_divergence(gm, x)
        assert torch.isfinite(div_s).all(), f"Divergence not finite: {div_s}"
        # For single Gaussian, div = -D/sigma^2 = -2 everywhere
        torch.testing.assert_close(
            div_s, torch.tensor([-2.0], dtype=torch.float64), atol=1e-4, rtol=1e-4)


# ===================================================================
# 3. gm_kernel_stein_discrepancy — KSD with IMQ kernel
# ===================================================================
class TestKSD:
    def test_ksd_self_near_zero(self):
        """KSD^2(p, samples_from_p) should be approximately 0."""
        torch.manual_seed(42)
        gm = _make_gm([[0.0, 0.0]], 0.0, [0.0])
        # Direct N(0,I) samples
        samples = torch.randn(1, 500, 2, dtype=torch.float64)
        ksd_sq = gm_kernel_stein_discrepancy(gm, samples)
        assert ksd_sq.item() < 0.05, (
            f"KSD^2(p, p_samples) should be near 0, got {ksd_sq.item():.4f}")

    def test_ksd_mean_shift_positive(self):
        """KSD^2(p, q_samples) should be large when means differ."""
        torch.manual_seed(42)
        gm_p = _make_gm([[0.0, 0.0]], 0.0, [0.0])
        # Samples from N([5,5], I)
        samples_q = torch.randn(1, 500, 2, dtype=torch.float64) + \
            torch.tensor([[[5.0, 5.0]]], dtype=torch.float64)
        ksd_sq = gm_kernel_stein_discrepancy(gm_p, samples_q)
        assert ksd_sq.item() > 0.5, (
            f"KSD^2(p, q_samples) should be large for shifted means, got {ksd_sq.item():.4f}")

    def test_ksd_variance_mismatch(self):
        """KSD should detect when samples have wrong variance."""
        torch.manual_seed(42)
        gm_p = _make_gm([[0.0, 0.0]], 0.0, [0.0])    # sigma=1
        sigma_q = math.exp(1.0)  # sigma=e~2.72
        # Samples from N(0, e^2 I)
        samples_q = sigma_q * torch.randn(1, 500, 2, dtype=torch.float64)
        ksd_sq = gm_kernel_stein_discrepancy(gm_p, samples_q)
        assert ksd_sq.item() > 0.01, (
            f"KSD should detect variance mismatch, got {ksd_sq.item():.4f}")

    def test_ksd_multimodal_self(self):
        """KSD^2 for a multimodal GM with its own samples should be near 0."""
        torch.manual_seed(42)
        gm = _make_gm([[-3.0, 0.0], [3.0, 0.0]], 0.0, [0.0, 0.0])
        # Direct sampling: 400 from each component (sigma=1)
        mu1 = torch.tensor([-3.0, 0.0], dtype=torch.float64)
        mu2 = torch.tensor([3.0, 0.0], dtype=torch.float64)
        s1 = mu1 + torch.randn(400, 2, dtype=torch.float64)
        s2 = mu2 + torch.randn(400, 2, dtype=torch.float64)
        samples = torch.cat([s1, s2], dim=0).unsqueeze(0)  # (1, 800, 2)
        ksd_sq = gm_kernel_stein_discrepancy(gm, samples)
        assert ksd_sq.item() < 0.1, (
            f"KSD^2(multimodal, own samples) should be near 0, got {ksd_sq.item():.4f}")

    def test_ksd_nonnegative(self):
        """KSD^2 should always be non-negative."""
        torch.manual_seed(42)
        gm = _make_gm([[0.0]], 0.0, [0.0])
        # D=1 samples from N(0, 1)
        samples = torch.randn(1, 200, 1, dtype=torch.float64)
        ksd_sq = gm_kernel_stein_discrepancy(gm, samples)
        assert ksd_sq.item() >= -1e-10, (
            f"KSD^2 should be non-negative, got {ksd_sq.item():.6f}")

    def test_ksd_monotone_with_shift(self):
        """Larger mean shift should produce larger KSD^2."""
        torch.manual_seed(42)
        gm_p = _make_gm([[0.0, 0.0]], 0.0, [0.0])
        # Samples from N([1,0], I) and N([3,0], I)
        s1 = torch.randn(1, 500, 2, dtype=torch.float64) + \
            torch.tensor([[[1.0, 0.0]]], dtype=torch.float64)
        s2 = torch.randn(1, 500, 2, dtype=torch.float64) + \
            torch.tensor([[[3.0, 0.0]]], dtype=torch.float64)
        ksd1 = gm_kernel_stein_discrepancy(gm_p, s1).item()
        ksd2 = gm_kernel_stein_discrepancy(gm_p, s2).item()
        assert ksd2 > ksd1, (
            f"Larger shift should yield larger KSD: shift=1 gave {ksd1:.4f}, shift=3 gave {ksd2:.4f}")
