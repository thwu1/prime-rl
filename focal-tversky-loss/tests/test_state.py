
"""
Tests for FocalTverskyLoss implementation and MONAI pipeline fixes.
"""

import sys
sys.path.insert(0, "/app")

import pytest
import torch
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Reference implementation — used as ground truth for loss function tests
# ---------------------------------------------------------------------------

def reference_ftl(
    input, target,
    alpha=0.7, beta=0.3, gamma=0.75, smooth=1.0,
    sigmoid=False, softmax=False,
    include_background=True, to_onehot_y=False,
    weight=None, batch=False, reduction="mean",
):
    """Independent reference implementation of Focal Tversky Loss."""
    p = input.clone().detach().float()

    if sigmoid:
        p = torch.sigmoid(p)
    elif softmax:
        p = F.softmax(p, dim=1)

    if to_onehot_y:
        num_classes = input.shape[1]
        t = target.squeeze(1).long()
        g = F.one_hot(t, num_classes)
        dims = [0, len(g.shape) - 1] + list(range(1, len(g.shape) - 1))
        g = g.permute(*dims).float()
    else:
        g = target.clone().detach().float()

    if not include_background:
        p = p[:, 1:]
        g = g[:, 1:]

    if batch:
        reduce_dims = [0] + list(range(2, p.dim()))
    else:
        reduce_dims = list(range(2, p.dim()))

    tp = (p * g).sum(dim=reduce_dims)
    fp = (p * (1 - g)).sum(dim=reduce_dims)
    fn = ((1 - p) * g).sum(dim=reduce_dims)

    ti = (tp + smooth) / (tp + alpha * fp + beta * fn + smooth)
    ftl = (1 - ti) ** gamma

    if weight is not None:
        w = torch.tensor(weight, dtype=ftl.dtype)
        ftl = ftl * w

    if reduction == "mean":
        return ftl.mean()
    elif reduction == "sum":
        return ftl.sum()
    else:
        return ftl


# ---------------------------------------------------------------------------
# FocalTverskyLoss tests
# ---------------------------------------------------------------------------

class TestFocalTverskyLoss:
    """Tests for the FocalTverskyLoss class implementation."""

    def _get_loss_class(self):
        from losses import FocalTverskyLoss
        return FocalTverskyLoss

    # -- basic cases --

    def test_basic_binary_sigmoid(self):
        FTL = self._get_loss_class()
        torch.manual_seed(42)
        inp = torch.randn(2, 1, 4, 4)
        tgt = (torch.rand(2, 1, 4, 4) > 0.5).float()

        result = FTL(alpha=0.7, beta=0.3, gamma=0.75, smooth=1.0, sigmoid=True)(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.7, beta=0.3, gamma=0.75,
                                 smooth=1.0, sigmoid=True)
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Expected {expected.item():.6f}, got {result.item():.6f}"
        )

    def test_multiclass_softmax(self):
        FTL = self._get_loss_class()
        torch.manual_seed(123)
        inp = torch.randn(2, 4, 8, 8)
        labels = torch.randint(0, 4, (2, 8, 8))
        tgt = F.one_hot(labels, 4).permute(0, 3, 1, 2).float()

        result = FTL(alpha=0.5, beta=0.5, gamma=1.0, smooth=1e-5, softmax=True)(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.5, beta=0.5, gamma=1.0,
                                 smooth=1e-5, softmax=True)
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Expected {expected.item():.6f}, got {result.item():.6f}"
        )

    # -- one-hot conversion --

    def test_onehot_conversion(self):
        FTL = self._get_loss_class()
        torch.manual_seed(7)
        inp = torch.randn(2, 3, 6, 6)
        tgt = torch.randint(0, 3, (2, 1, 6, 6))

        result = FTL(alpha=0.3, beta=0.7, gamma=0.5, softmax=True, to_onehot_y=True)(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.3, beta=0.7, gamma=0.5,
                                 softmax=True, to_onehot_y=True)
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Expected {expected.item():.6f}, got {result.item():.6f}"
        )

    # -- background exclusion --

    def test_exclude_background(self):
        FTL = self._get_loss_class()
        torch.manual_seed(99)
        inp = torch.randn(2, 3, 6, 6)
        tgt = torch.randint(0, 3, (2, 1, 6, 6))

        result = FTL(alpha=0.7, beta=0.3, gamma=0.75, softmax=True,
                     to_onehot_y=True, include_background=False)(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.7, beta=0.3, gamma=0.75,
                                 softmax=True, to_onehot_y=True, include_background=False)
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Expected {expected.item():.6f}, got {result.item():.6f}"
        )

    # -- class weights --

    def test_class_weights(self):
        FTL = self._get_loss_class()
        torch.manual_seed(55)
        inp = torch.randn(2, 3, 6, 6)
        tgt = torch.randint(0, 3, (2, 1, 6, 6))
        w = [0.5, 1.0, 2.0]

        result = FTL(alpha=0.7, beta=0.3, gamma=0.75, softmax=True,
                     to_onehot_y=True, weight=w)(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.7, beta=0.3, gamma=0.75,
                                 softmax=True, to_onehot_y=True, weight=w)
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Expected {expected.item():.6f}, got {result.item():.6f}"
        )

    def test_class_weights_exclude_background(self):
        FTL = self._get_loss_class()
        torch.manual_seed(66)
        inp = torch.randn(2, 3, 6, 6)
        tgt = torch.randint(0, 3, (2, 1, 6, 6))
        w = [1.0, 2.0]  # two weights for two non-background classes

        result = FTL(alpha=0.7, beta=0.3, gamma=0.75, softmax=True,
                     to_onehot_y=True, include_background=False, weight=w)(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.7, beta=0.3, gamma=0.75,
                                 softmax=True, to_onehot_y=True,
                                 include_background=False, weight=w)
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Expected {expected.item():.6f}, got {result.item():.6f}"
        )

    # -- batch mode --

    def test_batch_mode(self):
        FTL = self._get_loss_class()
        torch.manual_seed(33)
        inp = torch.randn(4, 2, 8, 8)
        tgt = (torch.rand(4, 2, 8, 8) > 0.5).float()

        result = FTL(alpha=0.7, beta=0.3, gamma=0.75, sigmoid=True, batch=True)(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.7, beta=0.3, gamma=0.75,
                                 sigmoid=True, batch=True)
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Expected {expected.item():.6f}, got {result.item():.6f}"
        )

    # -- focal gamma edge case --

    def test_focal_gamma_zero(self):
        """gamma=0 -> (1-TI)^0 = 1.0 for all classes."""
        FTL = self._get_loss_class()
        torch.manual_seed(11)
        inp = torch.randn(2, 2, 4, 4)
        tgt = (torch.rand(2, 2, 4, 4) > 0.5).float()

        result = FTL(alpha=0.5, beta=0.5, gamma=0.0, sigmoid=True)(inp, tgt)
        assert torch.allclose(result, torch.tensor(1.0), atol=1e-5), (
            f"Expected 1.0, got {result.item():.6f}"
        )

    # -- reduction modes --

    def test_reduction_sum(self):
        FTL = self._get_loss_class()
        torch.manual_seed(77)
        inp = torch.randn(3, 2, 4, 4)
        tgt = (torch.rand(3, 2, 4, 4) > 0.5).float()

        result = FTL(alpha=0.7, beta=0.3, gamma=0.75, sigmoid=True, reduction="sum")(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.7, beta=0.3, gamma=0.75,
                                 sigmoid=True, reduction="sum")
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Expected {expected.item():.6f}, got {result.item():.6f}"
        )

    def test_reduction_none(self):
        FTL = self._get_loss_class()
        torch.manual_seed(88)
        inp = torch.randn(3, 2, 4, 4)
        tgt = (torch.rand(3, 2, 4, 4) > 0.5).float()

        result = FTL(alpha=0.7, beta=0.3, gamma=0.75, sigmoid=True, reduction="none")(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.7, beta=0.3, gamma=0.75,
                                 sigmoid=True, reduction="none")
        assert result.shape == expected.shape, (
            f"Shape mismatch: {result.shape} vs {expected.shape}"
        )
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Values differ:\n  result={result}\n  expected={expected}"
        )

    # -- gradient flow --

    def test_gradient_flow(self):
        FTL = self._get_loss_class()
        inp = torch.randn(2, 3, 4, 4, requires_grad=True)
        tgt = torch.randint(0, 3, (2, 1, 4, 4))

        loss = FTL(alpha=0.7, beta=0.3, gamma=0.75, softmax=True, to_onehot_y=True)(inp, tgt)
        loss.backward()
        assert inp.grad is not None, "No gradient computed"
        assert not torch.isnan(inp.grad).any(), "NaN in gradients"
        assert not torch.isinf(inp.grad).any(), "Inf in gradients"

    # -- 3D spatial input --

    def test_3d_input(self):
        FTL = self._get_loss_class()
        torch.manual_seed(42)
        inp = torch.randn(2, 3, 4, 4, 4)
        tgt = torch.randint(0, 3, (2, 1, 4, 4, 4))

        result = FTL(alpha=0.7, beta=0.3, gamma=0.75, softmax=True, to_onehot_y=True)(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.7, beta=0.3, gamma=0.75,
                                 softmax=True, to_onehot_y=True)
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Expected {expected.item():.6f}, got {result.item():.6f}"
        )

    # -- 3D with background exclusion (combined stress test) --

    def test_3d_exclude_background(self):
        """3D input + one-hot + background exclusion — exercises all code paths."""
        FTL = self._get_loss_class()
        torch.manual_seed(101)
        inp = torch.randn(2, 4, 6, 6, 6)
        tgt = torch.randint(0, 4, (2, 1, 6, 6, 6))

        result = FTL(alpha=0.6, beta=0.4, gamma=0.5, softmax=True,
                     to_onehot_y=True, include_background=False)(inp, tgt)
        expected = reference_ftl(inp, tgt, alpha=0.6, beta=0.4, gamma=0.5,
                                 softmax=True, to_onehot_y=True,
                                 include_background=False)
        assert torch.allclose(result, expected, atol=1e-5), (
            f"Expected {expected.item():.6f}, got {result.item():.6f}"
        )

    # -- parameter validation --

    def test_parameter_validation(self):
        FTL = self._get_loss_class()
        with pytest.raises((ValueError, TypeError)):
            FTL(sigmoid=True, softmax=True)
        with pytest.raises(ValueError):
            FTL(reduction="invalid")


# ---------------------------------------------------------------------------
# MONAI pipeline tests
# ---------------------------------------------------------------------------

class TestPipelineFixes:
    """Tests for the MONAI evaluation pipeline."""

    def test_transforms_output_range(self):
        """After correct transforms, image values should be in [0, 1]."""
        from pipeline import create_synthetic_data, get_transforms

        data = create_synthetic_data(num_samples=1)
        transforms = get_transforms()
        result = transforms(data[0])
        img = result["image"]

        assert float(img.max()) > 0.1, (
            f"Image max is {float(img.max()):.6f} — values collapsed near zero"
        )
        assert float(img.min()) >= -0.01, (
            f"Image min is {float(img.min()):.6f} — expected >= 0"
        )
        assert float(img.max()) <= 1.01, (
            f"Image max is {float(img.max()):.6f} — expected <= 1"
        )

    def test_transforms_output_shape(self):
        """Transforms must produce correctly shaped tensors with a channel dimension."""
        from pipeline import create_synthetic_data, get_transforms

        data = create_synthetic_data(num_samples=1, spatial_size=(32, 32, 32))
        transforms = get_transforms()
        result = transforms(data[0])
        img = result["image"]
        lbl = result["label"]
        assert img.shape == (1, 32, 32, 32), (
            f"Image shape {tuple(img.shape)} — expected (1, 32, 32, 32)"
        )
        assert lbl.shape == (1, 32, 32, 32), (
            f"Label shape {tuple(lbl.shape)} — expected (1, 32, 32, 32)"
        )

    def test_model_accepts_3d_input(self):
        """Model must handle 3D volumetric (5-D tensor) input."""
        from pipeline import create_model

        model = create_model(num_classes=3)
        model.eval()
        x = torch.randn(1, 1, 32, 32, 32)
        with torch.no_grad():
            out = model(x)
        assert out.shape == (1, 3, 32, 32, 32), (
            f"Output shape {out.shape} — expected (1, 3, 32, 32, 32)"
        )

    def test_end_to_end_pipeline(self):
        """Full pipeline must run without crashing and return a valid metric."""
        from pipeline import run_evaluation

        result = run_evaluation(num_classes=3)
        assert isinstance(result, float), (
            f"Expected float metric, got {type(result)}"
        )
        assert result == result, (
            "Dice metric is NaN — pipeline has numerical issues"
        )
        assert result >= 0.0, (
            f"Dice metric is negative: {result}"
        )


# ---------------------------------------------------------------------------
# Integration test: training couples loss function with pipeline
# ---------------------------------------------------------------------------

class TestTrainingIntegration:
    """Tests that loss function and pipeline work together for training."""

    def test_training_convergence(self):
        """Training with FocalTverskyLoss must reduce loss and produce non-zero Dice."""
        from pipeline import train_and_evaluate

        losses, dice = train_and_evaluate(num_classes=3, num_epochs=5)

        # Loss values must be valid
        assert all(l == l for l in losses), (
            f"NaN in training losses: {losses}"
        )
        assert all(l >= 0 for l in losses), (
            f"Negative loss values: {losses}"
        )

        # Loss must decrease over training
        assert losses[-1] < losses[0], (
            f"Loss didn't decrease: first={losses[0]:.4f}, last={losses[-1]:.4f}"
        )

        # Dice must be valid and positive (model learned something)
        assert dice == dice, "Dice is NaN after training"
        assert dice > 0.0, (
            f"Model failed to learn: Dice={dice:.6f} — "
            f"loss function may compute wrong gradients"
        )
