"""
Comprehensive tests for the Needle deep learning framework.

"""

import sys
sys.path.insert(0, '/app')
import numpy as np
import pytest
import needle as ndl
import needle.nn as nn
from needle import ops


# ========================================================================== #
#  Utilities                                                                  #
# ========================================================================== #

def backward_check(f, *args, tol=1e-2, **kwargs):
    """Numerical gradient check using central differences."""
    eps = 1e-3
    np.random.seed(1)
    out = f(*args, **kwargs)
    if out.shape:
        c = np.random.randn(*out.shape).astype(np.float32)
    else:
        c = np.array(np.random.randn(), dtype=np.float32)
    numerical_grad = [np.zeros(a.shape, dtype=np.float32) for a in args]
    for i in range(len(args)):
        for j in range(args[i].realize_cached_data().size):
            args[i].realize_cached_data().flat[j] += eps
            f1 = (f(*args, **kwargs).numpy() * c).sum()
            args[i].realize_cached_data().flat[j] -= 2 * eps
            f2 = (f(*args, **kwargs).numpy() * c).sum()
            args[i].realize_cached_data().flat[j] += eps
            numerical_grad[i].flat[j] = (f1 - f2) / (2 * eps)
    out = f(*args, **kwargs)
    backward_grad = out.op.gradient_as_tuple(ndl.Tensor(c), out)
    error = sum(
        np.linalg.norm(backward_grad[i].numpy() - numerical_grad[i])
        for i in range(len(args))
    )
    assert error < tol, f"Backward check failed: error={error:.6f}"


def ref_sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def ref_lstm_cell(x, h, c, W_ih, W_hh, bias_ih=None, bias_hh=None):
    """Pure numpy reference for a single LSTM cell step."""
    hidden_size = h.shape[1]
    gates = x @ W_ih + h @ W_hh
    if bias_ih is not None:
        gates = gates + bias_ih
    if bias_hh is not None:
        gates = gates + bias_hh
    i = ref_sigmoid(gates[:, 0:hidden_size])
    f = ref_sigmoid(gates[:, hidden_size:2*hidden_size])
    g = np.tanh(gates[:, 2*hidden_size:3*hidden_size])
    o = ref_sigmoid(gates[:, 3*hidden_size:4*hidden_size])
    c_new = f * c + i * g
    h_new = o * np.tanh(c_new)
    return h_new, c_new


# ========================================================================== #
#  1. Autograd engine tests                                                   #
# ========================================================================== #

def test_topo_sort():
    from needle.autograd import find_topo_sort
    a = ndl.Tensor([1.0, 2.0], requires_grad=True)
    b = ndl.Tensor([3.0, 4.0], requires_grad=True)
    c = a + b
    d = c * a
    topo = find_topo_sort([d])
    assert topo[-1] is d
    assert topo.index(c) < topo.index(d)
    assert topo.index(a) < topo.index(c)
    assert topo.index(b) < topo.index(c)


def test_backward_simple():
    a = ndl.Tensor([2.0], requires_grad=True)
    b = ndl.Tensor([3.0], requires_grad=True)
    c = a * b
    c.backward()
    np.testing.assert_allclose(a.grad.numpy(), [3.0], atol=1e-5)
    np.testing.assert_allclose(b.grad.numpy(), [2.0], atol=1e-5)


def test_backward_complex():
    np.random.seed(0)
    x = ndl.Tensor([2.0, 3.0], requires_grad=True)
    y = x * x          # x^2
    z = y + x           # x^2 + x
    w = z.sum()          # sum(x^2 + x)
    w.backward()
    # dw/dx = 2x + 1
    np.testing.assert_allclose(x.grad.numpy(), [5.0, 7.0], atol=1e-5)


def test_backward_diamond():
    """Test gradient accumulation through a diamond-shaped graph."""
    x = ndl.Tensor([3.0], requires_grad=True)
    a = x * x    # x^2
    b = x + x    # 2x
    c = a + b    # x^2 + 2x
    c.backward()
    # dc/dx = 2x + 2 = 8
    np.testing.assert_allclose(x.grad.numpy(), [8.0], atol=1e-5)


# ========================================================================== #
#  2. Tensor operation tests                                                  #
# ========================================================================== #

def test_transpose_forward():
    np.random.seed(0)
    a = ndl.Tensor(np.random.randn(3, 4, 5).astype(np.float32))
    b = ops.transpose(a)
    np.testing.assert_allclose(b.numpy(), np.swapaxes(a.numpy(), -2, -1))
    c = ops.transpose(a, axes=(0, 2))
    np.testing.assert_allclose(c.numpy(), np.swapaxes(a.numpy(), 0, 2))


def test_transpose_backward():
    np.random.seed(0)
    backward_check(ops.transpose, ndl.Tensor(np.random.randn(3, 5).astype(np.float32)))
    backward_check(ops.transpose, ndl.Tensor(np.random.randn(3, 4, 5).astype(np.float32)),
                   axes=(0, 2))


def test_reshape_forward():
    np.random.seed(0)
    a = ndl.Tensor(np.random.randn(2, 3, 4).astype(np.float32))
    b = ops.reshape(a, (6, 4))
    np.testing.assert_allclose(b.numpy(), a.numpy().reshape(6, 4))
    c = ops.reshape(a, (24,))
    np.testing.assert_allclose(c.numpy(), a.numpy().reshape(24))


def test_reshape_backward():
    np.random.seed(0)
    backward_check(ops.reshape, ndl.Tensor(np.random.randn(2, 3, 4).astype(np.float32)),
                   shape=(6, 4))


def test_broadcast_forward():
    np.random.seed(0)
    a = ndl.Tensor(np.random.randn(3, 1).astype(np.float32))
    b = ops.broadcast_to(a, (3, 4))
    np.testing.assert_allclose(b.numpy(), np.broadcast_to(a.numpy(), (3, 4)))
    c = ndl.Tensor(np.random.randn(1,).astype(np.float32))
    d = ops.broadcast_to(c, (3, 4))
    np.testing.assert_allclose(d.numpy(), np.broadcast_to(c.numpy(), (3, 4)))


def test_broadcast_backward():
    np.random.seed(0)
    backward_check(ops.broadcast_to,
                   ndl.Tensor(np.random.randn(3, 1).astype(np.float32)),
                   shape=(3, 4))
    backward_check(ops.broadcast_to,
                   ndl.Tensor(np.random.randn(1,).astype(np.float32)),
                   shape=(3, 4))
    backward_check(ops.broadcast_to,
                   ndl.Tensor(np.random.randn(1, 1).astype(np.float32)),
                   shape=(3, 4))


def test_summation_forward():
    np.random.seed(0)
    a = ndl.Tensor(np.random.randn(3, 4, 5).astype(np.float32))
    np.testing.assert_allclose(ops.summation(a).numpy(), a.numpy().sum())
    np.testing.assert_allclose(ops.summation(a, axes=1).numpy(), a.numpy().sum(axis=1))
    np.testing.assert_allclose(ops.summation(a, axes=(0, 2)).numpy(), a.numpy().sum(axis=(0, 2)))


def test_summation_backward():
    np.random.seed(0)
    backward_check(ops.summation, ndl.Tensor(np.random.randn(3, 4).astype(np.float32)))
    backward_check(ops.summation, ndl.Tensor(np.random.randn(3, 4).astype(np.float32)),
                   axes=0)
    backward_check(ops.summation, ndl.Tensor(np.random.randn(3, 4).astype(np.float32)),
                   axes=1)
    backward_check(ops.summation, ndl.Tensor(np.random.randn(3, 4, 5).astype(np.float32)),
                   axes=(0, 2))


def test_matmul_forward():
    np.random.seed(0)
    a = ndl.Tensor(np.random.randn(3, 4).astype(np.float32))
    b = ndl.Tensor(np.random.randn(4, 5).astype(np.float32))
    np.testing.assert_allclose((a @ b).numpy(), a.numpy() @ b.numpy(), atol=1e-5)
    # Batched
    a2 = ndl.Tensor(np.random.randn(2, 3, 4).astype(np.float32))
    b2 = ndl.Tensor(np.random.randn(2, 4, 5).astype(np.float32))
    np.testing.assert_allclose((a2 @ b2).numpy(), a2.numpy() @ b2.numpy(), atol=1e-5)


def test_matmul_backward():
    np.random.seed(0)
    backward_check(ops.matmul,
                   ndl.Tensor(np.random.randn(3, 4).astype(np.float32)),
                   ndl.Tensor(np.random.randn(4, 5).astype(np.float32)))
    backward_check(ops.matmul,
                   ndl.Tensor(np.random.randn(2, 3, 4).astype(np.float32)),
                   ndl.Tensor(np.random.randn(2, 4, 5).astype(np.float32)))


def test_matmul_batched_broadcast_backward():
    """MatMul where one operand has fewer batch dims."""
    np.random.seed(0)
    backward_check(ops.matmul,
                   ndl.Tensor(np.random.randn(3, 4).astype(np.float32)),
                   ndl.Tensor(np.random.randn(2, 4, 5).astype(np.float32)),
                   tol=1e-1)


def test_log_exp_tanh_forward():
    np.random.seed(0)
    a = ndl.Tensor(np.abs(np.random.randn(3, 4).astype(np.float32)) + 0.1)
    np.testing.assert_allclose(ops.log(a).numpy(), np.log(a.numpy()), atol=1e-5)
    b = ndl.Tensor(np.random.randn(3, 4).astype(np.float32))
    np.testing.assert_allclose(ops.exp(b).numpy(), np.exp(b.numpy()), atol=1e-5)
    np.testing.assert_allclose(ops.tanh(b).numpy(), np.tanh(b.numpy()), atol=1e-5)


def test_log_backward():
    np.random.seed(0)
    backward_check(ops.log,
                   ndl.Tensor(np.abs(np.random.randn(3, 4).astype(np.float32)) + 0.5))


def test_exp_backward():
    np.random.seed(0)
    backward_check(ops.exp,
                   ndl.Tensor(np.random.randn(3, 4).astype(np.float32) * 0.5))


def test_tanh_backward():
    np.random.seed(0)
    backward_check(ops.tanh,
                   ndl.Tensor(np.random.randn(3, 4).astype(np.float32)))


# ========================================================================== #
#  3. Neural network module tests                                             #
# ========================================================================== #

def test_linear():
    np.random.seed(42)
    in_f, out_f, batch = 10, 5, 4
    x_np = np.random.randn(batch, in_f).astype(np.float32)

    layer = nn.Linear(in_f, out_f)
    w = layer.weight.numpy()   # (in_f, out_f)
    b = layer.bias.numpy()     # (1, out_f)

    ref = x_np @ w + b
    out = layer(ndl.Tensor(x_np))
    np.testing.assert_allclose(out.numpy(), ref, atol=1e-5)

    # Gradient flow
    out.sum().backward()
    assert layer.weight.grad is not None
    assert layer.bias.grad is not None


def test_layernorm():
    np.random.seed(42)
    batch, dim = 4, 8
    x_np = np.random.randn(batch, dim).astype(np.float32)

    layer = nn.LayerNorm1d(dim)
    w = layer.weight.numpy()
    b = layer.bias.numpy()

    mean = x_np.mean(axis=-1, keepdims=True)
    var = x_np.var(axis=-1, keepdims=True)
    ref = (x_np - mean) / np.sqrt(var + 1e-5) * w + b

    out = layer(ndl.Tensor(x_np))
    np.testing.assert_allclose(out.numpy(), ref, atol=1e-5)

    out.sum().backward()
    assert layer.weight.grad is not None


def test_softmax_loss():
    np.random.seed(42)
    batch, classes = 8, 5
    logits_np = np.random.randn(batch, classes).astype(np.float32)
    y_np = np.random.randint(0, classes, size=(batch,)).astype(np.float32)

    # Reference
    max_l = logits_np.max(axis=1, keepdims=True)
    shifted = logits_np - max_l
    lse = np.log(np.exp(shifted).sum(axis=1)) + max_l.flatten()
    correct = logits_np[np.arange(batch), y_np.astype(int)]
    ref_loss = np.mean(lse - correct)

    loss_fn = nn.SoftmaxLoss()
    loss = loss_fn(ndl.Tensor(logits_np), ndl.Tensor(y_np))
    np.testing.assert_allclose(loss.numpy(), ref_loss, atol=1e-4)


def test_sigmoid():
    np.random.seed(42)
    x_np = np.random.randn(4, 5).astype(np.float32)
    sig = nn.Sigmoid()
    out = sig(ndl.Tensor(x_np))
    ref = ref_sigmoid(x_np)
    np.testing.assert_allclose(out.numpy(), ref, atol=1e-5)


# ========================================================================== #
#  4. LSTM tests                                                              #
# ========================================================================== #

def test_lstm_cell():
    np.random.seed(42)
    batch, inp, hid = 4, 3, 5
    x_np = np.random.randn(batch, inp).astype(np.float32)
    h0_np = np.random.randn(batch, hid).astype(np.float32)
    c0_np = np.random.randn(batch, hid).astype(np.float32)

    cell = nn.LSTMCell(inp, hid)
    W_ih = cell.W_ih.numpy()
    W_hh = cell.W_hh.numpy()
    bias_ih = cell.bias_ih.numpy() if hasattr(cell, 'bias_ih') and cell.bias_ih is not None else None
    bias_hh = cell.bias_hh.numpy() if hasattr(cell, 'bias_hh') and cell.bias_hh is not None else None

    h_ndl, c_ndl = cell(ndl.Tensor(x_np),
                         (ndl.Tensor(h0_np), ndl.Tensor(c0_np)))
    h_ref, c_ref = ref_lstm_cell(x_np, h0_np, c0_np, W_ih, W_hh, bias_ih, bias_hh)

    np.testing.assert_allclose(h_ndl.numpy(), h_ref, atol=1e-5)
    np.testing.assert_allclose(c_ndl.numpy(), c_ref, atol=1e-5)


def test_lstm_cell_no_init():
    """LSTM cell with h=None (zeros)."""
    np.random.seed(42)
    batch, inp, hid = 4, 3, 5
    x_np = np.random.randn(batch, inp).astype(np.float32)
    cell = nn.LSTMCell(inp, hid)
    h, c = cell(ndl.Tensor(x_np))
    assert h.shape == (batch, hid)
    assert c.shape == (batch, hid)


def test_lstm_cell_gradient():
    """Verify gradients flow through LSTMCell."""
    np.random.seed(42)
    batch, inp, hid = 2, 3, 4
    x = ndl.Tensor(np.random.randn(batch, inp).astype(np.float32), requires_grad=True)
    cell = nn.LSTMCell(inp, hid)
    h, c = cell(x)
    h.sum().backward()
    assert x.grad is not None
    assert cell.W_ih.grad is not None
    assert cell.W_hh.grad is not None


def test_lstm():
    np.random.seed(42)
    seq_len, batch, inp, hid, layers = 5, 3, 4, 6, 2
    x_np = np.random.randn(seq_len, batch, inp).astype(np.float32)
    h0_np = np.random.randn(layers, batch, hid).astype(np.float32)
    c0_np = np.random.randn(layers, batch, hid).astype(np.float32)

    model = nn.LSTM(inp, hid, layers)

    output, (h_n, c_n) = model(
        ndl.Tensor(x_np),
        (ndl.Tensor(h0_np), ndl.Tensor(c0_np))
    )

    assert output.shape == (seq_len, batch, hid)
    assert h_n.shape == (layers, batch, hid)
    assert c_n.shape == (layers, batch, hid)

    # Reference forward pass using numpy
    # Extract weights
    cells = model.lstm_cells
    h_layers = [h0_np[l] for l in range(layers)]
    c_layers = [c0_np[l] for l in range(layers)]

    for t in range(seq_len):
        x_t = x_np[t]
        for l in range(layers):
            W_ih = cells[l].W_ih.numpy()
            W_hh = cells[l].W_hh.numpy()
            b_ih = cells[l].bias_ih.numpy() if hasattr(cells[l], 'bias_ih') and cells[l].bias_ih is not None else None
            b_hh = cells[l].bias_hh.numpy() if hasattr(cells[l], 'bias_hh') and cells[l].bias_hh is not None else None
            h_new, c_new = ref_lstm_cell(x_t, h_layers[l], c_layers[l], W_ih, W_hh, b_ih, b_hh)
            h_layers[l] = h_new
            c_layers[l] = c_new
            x_t = h_new

    # Check final hidden states
    for l in range(layers):
        np.testing.assert_allclose(h_n.numpy()[l], h_layers[l], atol=1e-4)
        np.testing.assert_allclose(c_n.numpy()[l], c_layers[l], atol=1e-4)


def test_lstm_gradient():
    """Verify gradients flow through multi-layer LSTM."""
    np.random.seed(42)
    seq_len, batch, inp, hid = 3, 2, 4, 5
    x = ndl.Tensor(np.random.randn(seq_len, batch, inp).astype(np.float32),
                    requires_grad=True)
    model = nn.LSTM(inp, hid, num_layers=2)
    output, _ = model(x)
    output.sum().backward()
    assert x.grad is not None
    for cell in model.lstm_cells:
        assert cell.W_ih.grad is not None
        assert cell.W_hh.grad is not None


def test_lstm_no_init():
    """LSTM with h=None."""
    np.random.seed(42)
    seq_len, batch, inp, hid = 4, 2, 3, 5
    model = nn.LSTM(inp, hid, num_layers=2)
    output, (h_n, c_n) = model(ndl.Tensor(np.random.randn(seq_len, batch, inp).astype(np.float32)))
    assert output.shape == (seq_len, batch, hid)
    assert h_n.shape == (2, batch, hid)


# ========================================================================== #
#  5. Embedding test                                                          #
# ========================================================================== #

def test_embedding():
    np.random.seed(42)
    vocab, dim = 10, 8
    emb = nn.Embedding(vocab, dim)
    w = emb.weight.numpy()  # (vocab, dim)

    seq_len, batch = 5, 3
    indices = np.random.randint(0, vocab, (seq_len, batch)).astype(np.float32)
    out = emb(ndl.Tensor(indices))

    # Reference: one-hot matmul
    one_hot = np.eye(vocab, dtype=np.float32)[indices.astype(int)]
    ref = one_hot @ w
    np.testing.assert_allclose(out.numpy(), ref, atol=1e-5)


# ========================================================================== #
#  6. Adam optimizer test                                                     #
# ========================================================================== #

def test_adam():
    np.random.seed(42)
    in_f, out_f = 4, 3
    layer = nn.Linear(in_f, out_f)
    opt = ndl.optim.Adam(layer.parameters(), lr=0.01, weight_decay=0.001)

    x = ndl.Tensor(np.random.randn(2, in_f).astype(np.float32))
    y = layer(x)
    loss = y.sum()

    loss.backward()

    # Save pre-step values and gradients
    w_before = layer.weight.numpy().copy()
    b_before = layer.bias.numpy().copy()
    w_grad = layer.weight.grad.numpy().copy()
    b_grad = layer.bias.grad.numpy().copy()

    opt.step()

    # Reference Adam step
    beta1, beta2, eps, lr, wd = 0.9, 0.999, 1e-8, 0.01, 0.001
    t = 1
    for param_np, grad_np, param_tensor in [
        (w_before, w_grad, layer.weight),
        (b_before, b_grad, layer.bias),
    ]:
        g = grad_np + wd * param_np
        m = (1 - beta1) * g
        v = (1 - beta2) * g ** 2
        m_hat = m / (1 - beta1 ** t)
        v_hat = v / (1 - beta2 ** t)
        expected = param_np - lr * m_hat / (np.sqrt(v_hat) + eps)
        np.testing.assert_allclose(
            param_tensor.numpy(), expected, atol=1e-5,
            err_msg="Adam step mismatch"
        )


# ========================================================================== #
#  7. Language model test                                                     #
# ========================================================================== #

def test_language_model_shapes():
    sys.path.insert(0, '/app')
    from apps.models import LanguageModel

    np.random.seed(42)
    emb_size, vocab, hidden, layers = 16, 50, 32, 2
    seq_len, batch = 7, 4

    model = LanguageModel(emb_size, vocab, hidden, layers, seq_model='lstm')
    x = ndl.Tensor(np.random.randint(0, vocab, (seq_len, batch)).astype(np.float32))

    out, h = model(x)
    assert out.shape == (seq_len * batch, vocab), f"Expected ({seq_len*batch}, {vocab}), got {out.shape}"
    assert isinstance(h, tuple), "Hidden state should be a tuple (h_n, c_n)"
    h_n, c_n = h
    assert h_n.shape == (layers, batch, hidden)
    assert c_n.shape == (layers, batch, hidden)


def test_language_model_gradient():
    sys.path.insert(0, '/app')
    from apps.models import LanguageModel

    np.random.seed(42)
    emb_size, vocab, hidden, layers = 8, 20, 16, 1
    seq_len, batch = 5, 3

    model = LanguageModel(emb_size, vocab, hidden, layers, seq_model='lstm')
    x = ndl.Tensor(np.random.randint(0, vocab, (seq_len, batch)).astype(np.float32))

    out, _ = model(x)
    out.sum().backward()

    # Verify gradients exist for all parameters
    params = model.parameters()
    assert len(params) > 0
    for p in params:
        assert p.grad is not None, "All parameters should have gradients"


def test_language_model_with_hidden():
    """Test LanguageModel with pre-initialized hidden state."""
    sys.path.insert(0, '/app')
    from apps.models import LanguageModel

    np.random.seed(42)
    emb_size, vocab, hidden, layers = 8, 20, 16, 2
    seq_len, batch = 5, 3

    model = LanguageModel(emb_size, vocab, hidden, layers, seq_model='lstm')
    x = ndl.Tensor(np.random.randint(0, vocab, (seq_len, batch)).astype(np.float32))
    h0 = ndl.Tensor(np.random.randn(layers, batch, hidden).astype(np.float32))
    c0 = ndl.Tensor(np.random.randn(layers, batch, hidden).astype(np.float32))

    out, (h_n, c_n) = model(x, (h0, c0))
    assert out.shape == (seq_len * batch, vocab)
    assert h_n.shape == (layers, batch, hidden)
    assert c_n.shape == (layers, batch, hidden)
