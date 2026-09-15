"""
Tests for the Generalized Diffusion Framework implementation.

"""

import sys
import math
import pytest
import torch

sys.path.insert(0, "/app")

from diffusion import ElucidatedDiffusion
from unet import SimpleUNet


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def model():
    """Standard model without self-conditioning."""
    torch.manual_seed(42)
    net = SimpleUNet(channels=1, image_size=16, dim=16, self_condition=False)
    return ElucidatedDiffusion(
        net,
        image_size=16,
        channels=1,
        num_sample_steps=8,
        sigma_min=0.002,
        sigma_max=80,
        sigma_data=0.5,
        alpha=3,
        P_mean=-1.2,
        P_std=1.2,
        S_churn=80,
        S_tmin=0.05,
        S_tmax=50,
        S_noise=1.003,
    )


@pytest.fixture
def model_sc():
    """Model with self-conditioning enabled."""
    torch.manual_seed(42)
    net = SimpleUNet(channels=1, image_size=16, dim=16, self_condition=True)
    return ElucidatedDiffusion(
        net,
        image_size=16,
        channels=1,
        num_sample_steps=8,
        sigma_data=0.5,
    )


# ---------------------------------------------------------------------------
# Preconditioning functions  (spec Section 2, α=3)
# ---------------------------------------------------------------------------

class TestCSkip:
    def test_at_sigma_data(self, model):
        """c_skip(sigma_data) = sigma_data^3 / (2 * sigma_data^3) = 0.5."""
        result = model.c_skip(torch.tensor(0.5))
        assert abs(float(result) - 0.5) < 1e-6

    def test_at_sigma_one(self, model):
        """c_skip(1.0) = 0.125 / (1.0 + 0.125) = 1/9."""
        result = model.c_skip(torch.tensor(1.0))
        expected = 0.5**3 / (1.0**3 + 0.5**3)
        assert abs(float(result) - expected) < 1e-6

    def test_at_sigma_two(self, model):
        """c_skip(2.0) = 0.125 / (8.0 + 0.125)."""
        result = model.c_skip(torch.tensor(2.0))
        expected = 0.5**3 / (2.0**3 + 0.5**3)
        assert abs(float(result) - expected) < 1e-5

    def test_large_sigma_approaches_zero(self, model):
        result = model.c_skip(torch.tensor(100.0))
        assert float(result) < 0.001

    def test_small_sigma_approaches_one(self, model):
        result = model.c_skip(torch.tensor(0.001))
        assert float(result) > 0.99


class TestCOut:
    def test_at_sigma_data(self, model):
        # c_out(0.5) = 0.5 * 0.5 / (0.125 + 0.125)^(1/3)
        expected = 0.5 * 0.5 / (0.5**3 + 0.5**3) ** (1.0 / 3.0)
        result = model.c_out(torch.tensor(0.5))
        assert abs(float(result) - expected) < 1e-4

    def test_at_sigma_one(self, model):
        # c_out(1.0) = 1.0 * 0.5 / (1.0 + 0.125)^(1/3)
        expected = 1.0 * 0.5 / (1.0**3 + 0.5**3) ** (1.0 / 3.0)
        result = model.c_out(torch.tensor(1.0))
        assert abs(float(result) - expected) < 1e-4

    def test_at_sigma_two(self, model):
        # c_out(2.0) = 2.0 * 0.5 / (8.0 + 0.125)^(1/3)
        expected = 2.0 * 0.5 / (2.0**3 + 0.5**3) ** (1.0 / 3.0)
        result = model.c_out(torch.tensor(2.0))
        assert abs(float(result) - expected) < 1e-4


class TestCIn:
    def test_at_sigma_data(self, model):
        # c_in(0.5) = (0.125 + 0.125)^(-1/3)
        expected = (0.5**3 + 0.5**3) ** (-1.0 / 3.0)
        result = model.c_in(torch.tensor(0.5))
        assert abs(float(result) - expected) < 1e-4

    def test_at_sigma_one(self, model):
        # c_in(1.0) = (1.0 + 0.125)^(-1/3)
        expected = (1.0**3 + 0.5**3) ** (-1.0 / 3.0)
        result = model.c_in(torch.tensor(1.0))
        assert abs(float(result) - expected) < 1e-4

    def test_at_sigma_two(self, model):
        # c_in(2.0) = (8.0 + 0.125)^(-1/3)
        expected = (2.0**3 + 0.5**3) ** (-1.0 / 3.0)
        result = model.c_in(torch.tensor(2.0))
        assert abs(float(result) - expected) < 1e-4


class TestCNoise:
    def test_at_sigma_one(self, model):
        """c_noise(1.0) = tanh(ln(1.0)/4) = tanh(0) = 0."""
        result = model.c_noise(torch.tensor(1.0))
        assert abs(float(result)) < 1e-6

    def test_at_sigma_e(self, model):
        """c_noise(e) = tanh(ln(e)/4) = tanh(0.25)."""
        result = model.c_noise(torch.tensor(math.e))
        expected = math.tanh(0.25)
        assert abs(float(result) - expected) < 1e-4

    def test_at_small_sigma(self, model):
        """c_noise(0.1) = tanh(ln(0.1)/4)."""
        expected = math.tanh(math.log(0.1) / 4)
        result = model.c_noise(torch.tensor(0.1))
        assert abs(float(result) - expected) < 1e-4

    def test_saturation_at_extreme_sigma(self, model):
        """tanh conditioning saturates — value must remain in (-1, 1).
        Standard 0.25*ln(sigma) would give -2.30 at sigma=0.0001,
        but tanh must stay within bounds."""
        result = model.c_noise(torch.tensor(0.0001))
        expected = math.tanh(math.log(0.0001) / 4)
        assert abs(float(result) - expected) < 1e-3
        assert float(result) > -1.0, "Value < -1 indicates linear scaling, not tanh"


# ---------------------------------------------------------------------------
# Loss weight  (spec Section 5.2, α=3)
# ---------------------------------------------------------------------------

class TestLossWeight:
    def test_at_sigma_one(self, model):
        # (1.0^3 + 0.5^3)^(2/3) / (1.0 * 0.5)^2
        expected = (1.0**3 + 0.5**3) ** (2.0 / 3.0) / (1.0 * 0.5) ** 2
        result = model.loss_weight(torch.tensor(1.0))
        assert abs(float(result) - expected) < 1e-3

    def test_at_sigma_data(self, model):
        # (0.5^3 + 0.5^3)^(2/3) / (0.5 * 0.5)^2
        expected = (0.5**3 + 0.5**3) ** (2.0 / 3.0) / (0.5 * 0.5) ** 2
        result = model.loss_weight(torch.tensor(0.5))
        assert abs(float(result) - expected) < 1e-3

    def test_at_sigma_two(self, model):
        # (2.0^3 + 0.5^3)^(2/3) / (2.0 * 0.5)^2
        expected = (2.0**3 + 0.5**3) ** (2.0 / 3.0) / (2.0 * 0.5) ** 2
        result = model.loss_weight(torch.tensor(2.0))
        assert abs(float(result) - expected) < 1e-3


# ---------------------------------------------------------------------------
# Sample schedule  (spec Section 4, log-cosine)
# ---------------------------------------------------------------------------

class TestSampleSchedule:
    def test_length(self, model):
        sigmas = model.sample_schedule(8)
        assert len(sigmas) == 9  # N + 1 (padded with 0)

    def test_starts_at_sigma_max(self, model):
        sigmas = model.sample_schedule(8)
        assert abs(sigmas[0].item() - 80.0) < 0.1

    def test_ends_at_zero(self, model):
        sigmas = model.sample_schedule(8)
        assert sigmas[-1].item() == 0.0

    def test_second_to_last_near_sigma_min(self, model):
        sigmas = model.sample_schedule(8)
        assert abs(sigmas[-2].item() - 0.002) < 0.001

    def test_monotonically_decreasing(self, model):
        sigmas = model.sample_schedule(16)
        for i in range(len(sigmas) - 1):
            assert sigmas[i].item() >= sigmas[i + 1].item(), (
                f"Schedule not monotonically decreasing at index {i}: "
                f"{sigmas[i].item()} < {sigmas[i+1].item()}"
            )

    def test_geometric_mean_midpoint(self, model):
        """With log-cosine schedule, midpoint is geometric mean sqrt(sigma_max * sigma_min)."""
        sigmas = model.sample_schedule(5)
        # At i=2 (midpoint with N=5): w=0.5, sigma = sqrt(80 * 0.002) = 0.4
        expected = math.sqrt(80.0 * 0.002)
        assert abs(sigmas[2].item() - expected) / expected < 0.01

    def test_not_power_law_schedule(self, model):
        """Verify schedule uses log-cosine, not inverse-power interpolation."""
        sigmas = model.sample_schedule(5)
        mid = sigmas[2].item()
        # Log-cosine midpoint: sqrt(80 * 0.002) = 0.4
        # Power-law midpoint (rho=7): approximately 2.5
        assert mid < 1.0, "Midpoint should be < 1 for log-cosine schedule"


# ---------------------------------------------------------------------------
# Noise distribution  (spec Section 5.1)
# ---------------------------------------------------------------------------

class TestNoiseDistribution:
    def test_shape(self, model):
        sigmas = model.noise_distribution(64)
        assert sigmas.shape == (64,)

    def test_all_positive(self, model):
        sigmas = model.noise_distribution(64)
        assert (sigmas > 0).all()

    def test_log_normal_statistics(self, model):
        """Log of samples should have mean ≈ P_mean and std ≈ P_std."""
        torch.manual_seed(0)
        sigmas = model.noise_distribution(50000)
        log_sigmas = torch.log(sigmas)
        assert abs(log_sigmas.mean().item() - (-1.2)) < 0.05
        assert abs(log_sigmas.std().item() - 1.2) < 0.05


# ---------------------------------------------------------------------------
# Preconditioned forward  (spec Section 3)
# ---------------------------------------------------------------------------

class TestPreconditionedForward:
    def test_output_shape(self, model):
        x = torch.randn(2, 1, 16, 16)
        out = model.preconditioned_network_forward(x, 1.0)
        assert out.shape == (2, 1, 16, 16)

    def test_float_sigma(self, model):
        """Should accept sigma as a Python float."""
        x = torch.randn(2, 1, 16, 16)
        out = model.preconditioned_network_forward(x, 0.5)
        assert out.shape == (2, 1, 16, 16)

    def test_tensor_sigma(self, model):
        """Should accept sigma as a (B,) tensor."""
        x = torch.randn(2, 1, 16, 16)
        sigma = torch.tensor([0.5, 1.0])
        out = model.preconditioned_network_forward(x, sigma)
        assert out.shape == (2, 1, 16, 16)

    def test_deterministic(self, model):
        x = torch.randn(2, 1, 16, 16)
        model.eval()
        out1 = model.preconditioned_network_forward(x, 1.0)
        out2 = model.preconditioned_network_forward(x, 1.0)
        assert torch.allclose(out1, out2)

    def test_different_sigma_different_output(self, model):
        x = torch.randn(2, 1, 16, 16)
        model.eval()
        out_low = model.preconditioned_network_forward(x, 0.01)
        out_high = model.preconditioned_network_forward(x, 50.0)
        assert not torch.allclose(out_low, out_high, atol=1e-3)

    def test_clamp(self, model):
        x = torch.randn(2, 1, 16, 16) * 100
        out = model.preconditioned_network_forward(x, 1.0, clamp=True)
        assert out.min() >= -1.0
        assert out.max() <= 1.0


# ---------------------------------------------------------------------------
# Training forward  (spec Section 5.3)
# ---------------------------------------------------------------------------

class TestTraining:
    def test_returns_scalar(self, model):
        torch.manual_seed(0)
        images = torch.rand(4, 1, 16, 16)
        loss = model(images)
        assert loss.dim() == 0
        assert loss.item() > 0

    def test_gradients_flow(self, model):
        torch.manual_seed(0)
        images = torch.rand(4, 1, 16, 16)
        loss = model(images)
        loss.backward()
        grad_exists = any(
            p.grad is not None and p.grad.abs().sum() > 0
            for p in model.parameters()
        )
        assert grad_exists, "No gradients flowed to model parameters"

    def test_with_self_conditioning(self, model_sc):
        """Training with self-conditioning should produce valid loss."""
        import random as pyrandom
        torch.manual_seed(0)
        pyrandom.seed(0)
        images = torch.rand(4, 1, 16, 16)
        loss = model_sc(images)
        assert loss.dim() == 0
        assert loss.item() > 0
        assert not torch.isnan(loss)


# ---------------------------------------------------------------------------
# Heun sampler  (spec Section 6)
# ---------------------------------------------------------------------------

class TestHeunSampler:
    def test_output_shape(self, model):
        torch.manual_seed(0)
        samples = model.sample(batch_size=2, num_sample_steps=4, clamp=True)
        assert samples.shape == (2, 1, 16, 16)

    def test_output_range(self, model):
        torch.manual_seed(0)
        samples = model.sample(batch_size=2, num_sample_steps=4, clamp=True)
        assert samples.min() >= 0.0, f"Min value {samples.min()} < 0"
        assert samples.max() <= 1.0, f"Max value {samples.max()} > 1"

    def test_deterministic(self, model):
        torch.manual_seed(0)
        s1 = model.sample(batch_size=2, num_sample_steps=4, clamp=True)
        torch.manual_seed(0)
        s2 = model.sample(batch_size=2, num_sample_steps=4, clamp=True)
        assert torch.allclose(s1, s2, atol=1e-5)

    def test_not_constant(self, model):
        """Samples should have meaningful variation, not be all zeros/ones."""
        torch.manual_seed(0)
        samples = model.sample(batch_size=2, num_sample_steps=4, clamp=True)
        assert samples.std() > 0.01, "Samples appear to be constant"


# ---------------------------------------------------------------------------
# DPM++ sampler  (spec Section 7)
# ---------------------------------------------------------------------------

class TestDPMPPSampler:
    def test_output_shape(self, model):
        torch.manual_seed(0)
        samples = model.sample_using_dpmpp(batch_size=2, num_sample_steps=4)
        assert samples.shape == (2, 1, 16, 16)

    def test_output_range(self, model):
        torch.manual_seed(0)
        samples = model.sample_using_dpmpp(batch_size=2, num_sample_steps=4)
        assert samples.min() >= 0.0
        assert samples.max() <= 1.0

    def test_deterministic(self, model):
        torch.manual_seed(0)
        s1 = model.sample_using_dpmpp(batch_size=2, num_sample_steps=4)
        torch.manual_seed(0)
        s2 = model.sample_using_dpmpp(batch_size=2, num_sample_steps=4)
        assert torch.allclose(s1, s2, atol=1e-5)

    def test_differs_from_heun(self, model):
        """DPM++ and Heun use different algorithms; outputs must differ."""
        torch.manual_seed(0)
        s_heun = model.sample(batch_size=2, num_sample_steps=4, clamp=True)
        torch.manual_seed(0)
        s_dpmpp = model.sample_using_dpmpp(batch_size=2, num_sample_steps=4)
        assert not torch.allclose(s_heun, s_dpmpp, atol=1e-2)
