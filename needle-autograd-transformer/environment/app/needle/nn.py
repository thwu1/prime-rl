"""Neural network modules for the Needle framework.

Implement all classes marked with ``raise NotImplementedError()``.
Use operations from ``ops.py`` (via the ``ops`` module) so that all
computations flow through the autograd engine.
"""

import numpy as np
from .autograd import Tensor
from . import ops, init


class Parameter(Tensor):
    """A Tensor that represents a learnable parameter."""
    pass


class Module:
    """Base class for all neural-network modules."""

    def __init__(self):
        self.training = True

    def parameters(self):
        """Collect all Parameters in this module and its children."""
        params = []
        for attr in self.__dict__.values():
            if isinstance(attr, Parameter):
                params.append(attr)
            elif isinstance(attr, Module):
                params.extend(attr.parameters())
            elif isinstance(attr, (list, tuple)):
                for item in attr:
                    if isinstance(item, Parameter):
                        params.append(item)
                    elif isinstance(item, Module):
                        params.extend(item.parameters())
        return params

    def train(self):
        self.training = True
        for attr in self.__dict__.values():
            if isinstance(attr, Module):
                attr.train()
            elif isinstance(attr, (list, tuple)):
                for item in attr:
                    if isinstance(item, Module):
                        item.train()
        return self

    def eval(self):
        self.training = False
        for attr in self.__dict__.values():
            if isinstance(attr, Module):
                attr.eval()
            elif isinstance(attr, (list, tuple)):
                for item in attr:
                    if isinstance(item, Module):
                        item.eval()
        return self

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)

    def forward(self, *args, **kwargs):
        raise NotImplementedError()


# ---------------------------------------------------------------------------
#  TO IMPLEMENT
# ---------------------------------------------------------------------------

class Linear(Module):
    """Fully-connected linear layer: y = x @ W + b.

    Attributes (to create):
        weight: Parameter of shape (in_features, out_features),
                initialized with Kaiming uniform.
        bias:   Parameter of shape (out_features,), initialized with
                uniform(-1/sqrt(in_features), 1/sqrt(in_features)).
                Omitted when bias=False.
    """

    def __init__(self, in_features, out_features, bias=True):
        super().__init__()
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def forward(self, x: Tensor) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class ReLUModule(Module):
    """ReLU activation as a module wrapper."""

    def forward(self, x: Tensor) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class LayerNorm(Module):
    """Layer normalization over the last dimension.

    Given input x of shape (..., features):
      1. mean = mean of x along last axis
      2. var  = population variance of x along last axis
      3. x_hat = (x - mean) / sqrt(var + eps)
      4. output = weight * x_hat + bias

    weight (init ones) and bias (init zeros) have shape (features,).
    """

    def __init__(self, features, eps=1e-5):
        super().__init__()
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def forward(self, x: Tensor) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Dropout(Module):
    """Inverted dropout.

    During training: zero-out each element independently with probability p,
    then scale surviving elements by 1/(1-p).
    During evaluation: identity.
    """

    def __init__(self, p=0.0):
        super().__init__()
        self.p = p

    def forward(self, x: Tensor) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class SoftmaxLoss(Module):
    """Cross-entropy loss with numerically-stable log-softmax.

    forward(logits, targets):
        logits  – Tensor of shape (batch, num_classes)
        targets – numpy int array of shape (batch,) with class indices

    Returns a scalar Tensor (mean loss over the batch).
    """

    def forward(self, logits: Tensor, targets: np.ndarray) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Residual(Module):
    """Residual wrapper: output = x + fn(x)."""

    def __init__(self, fn: Module):
        super().__init__()
        self.fn = fn

    def forward(self, x: Tensor) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class MultiHeadAttention(Module):
    """Multi-head (optionally causal) self-attention.

    Given input x of shape (batch, seq_len, embed_dim):
      1. Project to Q, K, V via three separate Linear layers (no bias).
      2. Reshape to (batch, num_heads, seq_len, head_dim).
      3. Compute scaled dot-product attention:
            scores = Q K^T / sqrt(head_dim)
         If causal, mask future positions with -1e9 before softmax.
      4. attn_weights = softmax(scores, axis=-1)   (use detached max for
         numerical stability, then exp/sum through the autograd graph).
      5. Apply dropout to attn_weights.
      6. context = attn_weights @ V
      7. Concatenate heads → (batch, seq_len, embed_dim).
      8. Output projection via a Linear layer (no bias).
    """

    def __init__(self, embed_dim, num_heads, causal=True, dropout=0.0):
        super().__init__()
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def forward(self, x: Tensor) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class TransformerLayer(Module):
    """Pre-norm Transformer encoder layer.

    Architecture (prenorm with residual connections):
      x = x + dropout( attention( layernorm1(x) ) )
      x = x + dropout( linear2( relu( linear1( layernorm2(x) ) ) ) )

    linear1: embed_dim → hidden_dim
    linear2: hidden_dim → embed_dim
    """

    def __init__(self, embed_dim, num_heads, hidden_dim, causal=True, dropout=0.0):
        super().__init__()
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def forward(self, x: Tensor) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION
