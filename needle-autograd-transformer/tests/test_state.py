"""Tests for the Needle deep learning framework.

Verifies both forward-pass correctness (against NumPy references) and
backward-pass correctness (via numerical gradient checking with finite
differences) for all operations and neural-network modules.
"""

import sys
sys.path.insert(0, "/app")

import pytest
import numpy as np
from needle.autograd import Tensor
from needle import ops, nn


# =========================================================================
#  Gradient-checking utility
# =========================================================================

def gradient_check(f, *args, tol=1e-4, h=1e-5):
    """Compare autograd gradients with numerical finite differences.

    ``f`` takes one or more Tensor arguments and returns a Tensor of any
    shape.  The check verifies d(sum(f)) / d(arg_i) for each argument.
    All computations are done in float64 for accuracy.
    """
    args64 = [np.array(a, dtype="float64") for a in args]
    tensors = [Tensor(a, requires_grad=True) for a in args64]
    output = f(*tensors)
    output.backward()

    for idx in range(len(args64)):
        auto_grad = tensors[idx].grad.numpy()
        a_orig = args64[idx].copy()
        num_grad = np.zeros_like(a_orig)
        it = np.nditer(num_grad, flags=["multi_index"])
        while not it.finished:
            mi = it.multi_index
            a_plus = a_orig.copy()
            a_plus[mi] += h
            a_minus = a_orig.copy()
            a_minus[mi] -= h

            ap = [a.copy() for a in args64]
            ap[idx] = a_plus
            tp = [Tensor(x, requires_grad=False) for x in ap]
            fp = f(*tp).numpy().sum()

            am = [a.copy() for a in args64]
            am[idx] = a_minus
            tm = [Tensor(x, requires_grad=False) for x in am]
            fm = f(*tm).numpy().sum()

            num_grad[mi] = (fp - fm) / (2 * h)
            it.iternext()

        np.testing.assert_allclose(
            auto_grad, num_grad, atol=tol, rtol=tol,
            err_msg=f"Gradient check FAILED for argument {idx}",
        )


# =========================================================================
#  Basic unary / scalar ops – forward + gradient
# =========================================================================

class TestBasicOps:
    def test_negate(self):
        np.random.seed(0)
        a = np.random.randn(3, 4).astype("float32")
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(ops.Negate()(t).numpy(), -a, atol=1e-6)
        gradient_check(lambda x: ops.Negate()(x), a)

    def test_log(self):
        np.random.seed(1)
        a = np.abs(np.random.randn(3, 4).astype("float32")) + 0.1
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(ops.Log()(t).numpy(), np.log(a), atol=1e-5)
        gradient_check(lambda x: ops.Log()(x), a)

    def test_exp(self):
        np.random.seed(2)
        a = np.random.randn(3, 4).astype("float32") * 0.5
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(ops.Exp()(t).numpy(), np.exp(a), atol=1e-5)
        gradient_check(lambda x: ops.Exp()(x), a)

    def test_relu(self):
        np.random.seed(3)
        a = np.random.randn(4, 5).astype("float32")
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.ReLU()(t).numpy(), np.maximum(a, 0), atol=1e-6
        )
        # avoid exact zeros where gradient is undefined
        a_safe = a.copy()
        a_safe[np.abs(a_safe) < 0.05] = 0.5
        gradient_check(lambda x: ops.ReLU()(x), a_safe)

    def test_tanh(self):
        np.random.seed(4)
        a = np.random.randn(3, 4).astype("float32")
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.Tanh()(t).numpy(), np.tanh(a), atol=1e-5
        )
        gradient_check(lambda x: ops.Tanh()(x), a)

    def test_power_scalar(self):
        np.random.seed(5)
        a = np.abs(np.random.randn(3, 4).astype("float32")) + 0.5
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.PowerScalar(3)(t).numpy(), a ** 3, atol=1e-3
        )
        gradient_check(lambda x: ops.PowerScalar(3)(x), a)

    def test_power_scalar_fractional(self):
        np.random.seed(50)
        a = np.abs(np.random.randn(3, 4).astype("float32")) + 0.5
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.PowerScalar(0.5)(t).numpy(), a ** 0.5, atol=1e-5
        )
        gradient_check(lambda x: ops.PowerScalar(0.5)(x), a)

    def test_div_scalar(self):
        np.random.seed(6)
        a = np.random.randn(3, 4).astype("float32")
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.DivScalar(3.0)(t).numpy(), a / 3.0, atol=1e-6
        )
        gradient_check(lambda x: ops.DivScalar(3.0)(x), a)

    def test_ewise_div(self):
        np.random.seed(7)
        a = np.random.randn(3, 4).astype("float32")
        b = np.random.randn(3, 4).astype("float32") + 2.0
        ta = Tensor(a, requires_grad=False)
        tb = Tensor(b, requires_grad=False)
        np.testing.assert_allclose(
            ops.EWiseDiv()(ta, tb).numpy(), a / b, atol=1e-5
        )
        gradient_check(lambda x, y: ops.EWiseDiv()(x, y), a, b)


# =========================================================================
#  Shape-manipulation ops – forward + gradient
# =========================================================================

class TestShapeOps:
    def test_transpose_default(self):
        np.random.seed(10)
        a = np.random.randn(3, 4, 5).astype("float32")
        t = Tensor(a, requires_grad=False)
        expected = np.swapaxes(a, -2, -1)
        np.testing.assert_allclose(
            ops.Transpose()(t).numpy(), expected, atol=1e-6
        )
        gradient_check(lambda x: ops.Transpose()(x), a)

    def test_transpose_specific(self):
        np.random.seed(11)
        a = np.random.randn(2, 3, 4, 5).astype("float32")
        t = Tensor(a, requires_grad=False)
        expected = np.swapaxes(a, 0, 2)
        np.testing.assert_allclose(
            ops.Transpose((0, 2))(t).numpy(), expected, atol=1e-6
        )
        gradient_check(lambda x: ops.Transpose((0, 2))(x), a)

    def test_reshape(self):
        np.random.seed(12)
        a = np.random.randn(3, 4, 5).astype("float32")
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.Reshape((12, 5))(t).numpy(), a.reshape(12, 5), atol=1e-6
        )
        gradient_check(lambda x: ops.Reshape((12, 5))(x), a)

    def test_broadcast_to(self):
        np.random.seed(13)
        a = np.random.randn(1, 4).astype("float32")
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.BroadcastTo((3, 4))(t).numpy(),
            np.broadcast_to(a, (3, 4)),
            atol=1e-6,
        )
        gradient_check(lambda x: ops.BroadcastTo((3, 4))(x), a)

    def test_broadcast_add_dims(self):
        """Broadcast from (4,) to (3, 4) — leading dimension added."""
        np.random.seed(14)
        a = np.random.randn(4).astype("float32")
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.BroadcastTo((3, 4))(t).numpy(),
            np.broadcast_to(a, (3, 4)),
            atol=1e-6,
        )
        gradient_check(lambda x: ops.BroadcastTo((3, 4))(x), a)

    def test_broadcast_multi_dim(self):
        """Broadcast from (3, 1) to (3, 5) — inner dimension expanded."""
        np.random.seed(15)
        a = np.random.randn(3, 1).astype("float32")
        gradient_check(lambda x: ops.BroadcastTo((3, 5))(x), a)

    def test_summation_all(self):
        np.random.seed(20)
        a = np.random.randn(3, 4).astype("float32")
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.Summation()(t).numpy(), a.sum(), atol=1e-5
        )
        gradient_check(lambda x: ops.Summation()(x), a)

    def test_summation_single_axis(self):
        np.random.seed(21)
        a = np.random.randn(3, 4, 5).astype("float32")
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.Summation(1)(t).numpy(), a.sum(axis=1), atol=1e-5
        )
        gradient_check(lambda x: ops.Summation(1)(x), a)

    def test_summation_tuple_axes(self):
        np.random.seed(22)
        a = np.random.randn(3, 4, 5).astype("float32")
        t = Tensor(a, requires_grad=False)
        np.testing.assert_allclose(
            ops.Summation((0, 2))(t).numpy(), a.sum(axis=(0, 2)), atol=1e-5
        )
        gradient_check(lambda x: ops.Summation((0, 2))(x), a)


# =========================================================================
#  MatMul – forward + gradient (including broadcasting)
# =========================================================================

class TestMatMul:
    def test_matmul_2d(self):
        np.random.seed(30)
        a = np.random.randn(3, 4).astype("float32")
        b = np.random.randn(4, 5).astype("float32")
        ta = Tensor(a, requires_grad=False)
        tb = Tensor(b, requires_grad=False)
        np.testing.assert_allclose(
            ops.MatMul()(ta, tb).numpy(), a @ b, atol=1e-5
        )
        gradient_check(lambda x, y: ops.MatMul()(x, y), a, b)

    def test_matmul_3d_2d(self):
        """Batched @ non-batched: grad of b must sum over batch dim."""
        np.random.seed(31)
        a = np.random.randn(2, 3, 4).astype("float32")
        b = np.random.randn(4, 5).astype("float32")
        ta = Tensor(a, requires_grad=False)
        tb = Tensor(b, requires_grad=False)
        np.testing.assert_allclose(
            ops.MatMul()(ta, tb).numpy(), a @ b, atol=1e-5
        )
        gradient_check(lambda x, y: ops.MatMul()(x, y), a, b)

    def test_matmul_2d_3d(self):
        """Non-batched @ batched: grad of a must sum over batch dim."""
        np.random.seed(32)
        a = np.random.randn(3, 4).astype("float32")
        b = np.random.randn(2, 4, 5).astype("float32")
        ta = Tensor(a, requires_grad=False)
        tb = Tensor(b, requires_grad=False)
        np.testing.assert_allclose(
            ops.MatMul()(ta, tb).numpy(), a @ b, atol=1e-5
        )
        gradient_check(lambda x, y: ops.MatMul()(x, y), a, b)

    def test_matmul_batched(self):
        """Both batched with same batch size."""
        np.random.seed(33)
        a = np.random.randn(2, 3, 4).astype("float32")
        b = np.random.randn(2, 4, 5).astype("float32")
        ta = Tensor(a, requires_grad=False)
        tb = Tensor(b, requires_grad=False)
        np.testing.assert_allclose(
            ops.MatMul()(ta, tb).numpy(), a @ b, atol=1e-5
        )
        gradient_check(lambda x, y: ops.MatMul()(x, y), a, b)


# =========================================================================
#  Composed operations – gradient through a chain
# =========================================================================

class TestComposition:
    def test_chain_ops(self):
        """Gradient through a non-trivial composition of ops."""
        np.random.seed(40)
        a = np.abs(np.random.randn(3, 4).astype("float32")) + 0.5
        b = np.abs(np.random.randn(3, 4).astype("float32")) + 0.5

        def f(x, y):
            # (x / y + 2)^2  summed
            return ((x / y + 2.0) ** 2).sum()

        gradient_check(f, a, b)

    def test_matmul_transpose_sum(self):
        """Gradient through matmul → transpose → sum chain."""
        np.random.seed(41)
        a = np.random.randn(3, 4).astype("float32")
        b = np.random.randn(4, 5).astype("float32")

        def f(x, y):
            return (x @ y).transpose().sum()

        gradient_check(f, a, b)


# =========================================================================
#  Neural-network modules
# =========================================================================

class TestModules:
    # ---- Linear ----
    def test_linear_forward(self):
        np.random.seed(100)
        layer = nn.Linear(5, 3)
        x = Tensor(np.random.randn(4, 5).astype("float32"))
        out = layer(x)
        assert out.shape == (4, 3)
        # manual reference
        expected = x.numpy() @ layer.weight.numpy()
        if hasattr(layer, "bias") and layer.bias is not None:
            expected += layer.bias.numpy()
        np.testing.assert_allclose(out.numpy(), expected, atol=1e-5)

    def test_linear_backward(self):
        np.random.seed(101)
        layer = nn.Linear(4, 3)
        x_np = np.random.randn(2, 4).astype("float32")
        gradient_check(lambda x: layer(x).sum(), x_np)

    def test_linear_3d(self):
        """Linear with 3-D input (batch, seq, features)."""
        np.random.seed(102)
        layer = nn.Linear(4, 3)
        x_np = np.random.randn(2, 5, 4).astype("float32")
        out = layer(Tensor(x_np))
        assert out.shape == (2, 5, 3)
        gradient_check(lambda x: layer(x).sum(), x_np)

    # ---- LayerNorm ----
    def test_layernorm_forward(self):
        np.random.seed(110)
        ln = nn.LayerNorm(5)
        x = np.random.randn(3, 5).astype("float32")
        out = ln(Tensor(x)).numpy()
        # reference (weight=1, bias=0)
        mean = x.mean(axis=-1, keepdims=True)
        var = x.var(axis=-1, keepdims=True)
        expected = (x - mean) / np.sqrt(var + 1e-5)
        np.testing.assert_allclose(out, expected, atol=1e-5)

    def test_layernorm_backward(self):
        np.random.seed(111)
        ln = nn.LayerNorm(4)
        x_np = np.random.randn(3, 4).astype("float32")
        gradient_check(lambda x: ln(x).sum(), x_np)

    def test_layernorm_3d(self):
        """LayerNorm with 3-D input (batch, seq, features)."""
        np.random.seed(112)
        ln = nn.LayerNorm(4)
        x_np = np.random.randn(2, 3, 4).astype("float32")
        out = ln(Tensor(x_np))
        assert out.shape == (2, 3, 4)
        gradient_check(lambda x: ln(x).sum(), x_np)

    # ---- SoftmaxLoss ----
    def test_softmax_loss_forward(self):
        np.random.seed(120)
        logits_np = np.random.randn(4, 5).astype("float32")
        targets = np.array([0, 3, 1, 4])
        loss_val = nn.SoftmaxLoss()(Tensor(logits_np), targets).numpy()
        # reference
        shifted = logits_np - logits_np.max(axis=1, keepdims=True)
        log_sum_exp = np.log(np.exp(shifted).sum(axis=1))
        ref = (log_sum_exp - shifted[np.arange(4), targets]).mean()
        np.testing.assert_allclose(float(loss_val), ref, atol=1e-5)

    def test_softmax_loss_backward(self):
        np.random.seed(121)
        logits_np = np.random.randn(3, 4).astype("float32")
        targets = np.array([0, 2, 1])

        def f(logits):
            return nn.SoftmaxLoss()(logits, targets)

        gradient_check(f, logits_np)

    # ---- Dropout (eval mode = identity) ----
    def test_dropout_eval(self):
        np.random.seed(130)
        dp = nn.Dropout(p=0.5)
        dp.eval()
        x = np.random.randn(3, 4).astype("float32")
        out = dp(Tensor(x)).numpy()
        np.testing.assert_allclose(out, x, atol=1e-6)

    # ---- Residual ----
    def test_residual(self):
        np.random.seed(140)
        layer = nn.Linear(4, 4)
        res = nn.Residual(layer)
        x_np = np.random.randn(2, 4).astype("float32")
        out = res(Tensor(x_np)).numpy()
        expected = x_np + (x_np @ layer.weight.numpy() + layer.bias.numpy())
        np.testing.assert_allclose(out, expected, atol=1e-5)
        gradient_check(lambda x: res(x).sum(), x_np)

    # ---- MultiHeadAttention ----
    def test_attention_shape(self):
        np.random.seed(200)
        attn = nn.MultiHeadAttention(
            embed_dim=8, num_heads=2, causal=True, dropout=0.0
        )
        attn.eval()
        x = Tensor(np.random.randn(2, 5, 8).astype("float32") * 0.1)
        out = attn(x)
        assert out.shape == (2, 5, 8)

    def test_attention_backward(self):
        np.random.seed(201)
        attn = nn.MultiHeadAttention(
            embed_dim=4, num_heads=2, causal=True, dropout=0.0
        )
        attn.eval()
        x_np = np.random.randn(2, 3, 4).astype("float32") * 0.1
        gradient_check(lambda x: attn(x).sum(), x_np, tol=5e-4, h=1e-5)

    def test_attention_no_causal(self):
        np.random.seed(202)
        attn = nn.MultiHeadAttention(
            embed_dim=4, num_heads=2, causal=False, dropout=0.0
        )
        attn.eval()
        x_np = np.random.randn(2, 3, 4).astype("float32") * 0.1
        gradient_check(lambda x: attn(x).sum(), x_np, tol=5e-4, h=1e-5)

    # ---- TransformerLayer ----
    def test_transformer_shape(self):
        np.random.seed(300)
        layer = nn.TransformerLayer(
            embed_dim=8, num_heads=2, hidden_dim=16,
            causal=True, dropout=0.0,
        )
        layer.eval()
        x = Tensor(np.random.randn(2, 4, 8).astype("float32") * 0.1)
        out = layer(x)
        assert out.shape == (2, 4, 8)

    def test_transformer_backward(self):
        np.random.seed(301)
        layer = nn.TransformerLayer(
            embed_dim=4, num_heads=2, hidden_dim=8,
            causal=True, dropout=0.0,
        )
        layer.eval()
        x_np = np.random.randn(1, 2, 4).astype("float32") * 0.1
        gradient_check(lambda x: layer(x).sum(), x_np, tol=5e-4, h=1e-5)

    def test_transformer_params_have_grad(self):
        """All parameters receive gradients after a backward pass."""
        np.random.seed(302)
        layer = nn.TransformerLayer(
            embed_dim=4, num_heads=2, hidden_dim=8,
            causal=True, dropout=0.0,
        )
        layer.eval()
        x = Tensor(np.random.randn(2, 3, 4).astype("float32") * 0.1)
        loss = layer(x).sum()
        loss.backward()
        for p in layer.parameters():
            assert p.grad is not None, "Parameter missing gradient"
            assert np.all(np.isfinite(p.grad.numpy())), "Non-finite gradient"
