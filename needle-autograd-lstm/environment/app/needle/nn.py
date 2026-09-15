"""Neural network modules."""
from typing import List, Any
from needle.autograd import Tensor
from needle import ops
import needle.init as init
import numpy as np


class Parameter(Tensor):
    """A special kind of tensor that represents parameters."""


def _unpack_params(value: object) -> List[Tensor]:
    if isinstance(value, Parameter):
        return [value]
    elif isinstance(value, Module):
        return value.parameters()
    elif isinstance(value, dict):
        params = []
        for k, v in value.items():
            params += _unpack_params(v)
        return params
    elif isinstance(value, (list, tuple)):
        params = []
        for v in value:
            params += _unpack_params(v)
        return params
    else:
        return []


def _child_modules(value: object) -> List["Module"]:
    if isinstance(value, Module):
        modules = [value]
        modules.extend(_child_modules(value.__dict__))
        return modules
    if isinstance(value, dict):
        modules = []
        for k, v in value.items():
            modules += _child_modules(v)
        return modules
    elif isinstance(value, (list, tuple)):
        modules = []
        for v in value:
            modules += _child_modules(v)
        return modules
    else:
        return []


class Module:
    def __init__(self):
        self.training = True

    def parameters(self) -> List[Tensor]:
        return _unpack_params(self.__dict__)

    def _children(self) -> List["Module"]:
        return _child_modules(self.__dict__)

    def eval(self):
        self.training = False
        for m in self._children():
            m.training = False

    def train(self):
        self.training = True
        for m in self._children():
            m.training = True

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)


# --------------------------------------------------------------------------- #
#  Modules to implement (stubs)                                               #
# --------------------------------------------------------------------------- #

class Linear(Module):
    def __init__(self, in_features: int, out_features: int, bias: bool = True,
                 device: Any = None, dtype: str = "float32"):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def forward(self, X: Tensor) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class LayerNorm1d(Module):
    def __init__(self, dim: int, eps: float = 1e-5, device: Any = None,
                 dtype: str = "float32"):
        super().__init__()
        self.dim = dim
        self.eps = eps
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def forward(self, x: Tensor) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class SoftmaxLoss(Module):
    def forward(self, logits: Tensor, y: Tensor) -> Tensor:
        """
        Args:
            logits: (batch_size, num_classes)
            y: (batch_size,) integer class labels
        Returns:
            Scalar mean cross-entropy loss.
        """
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Sigmoid(Module):
    def forward(self, x: Tensor) -> Tensor:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class LSTMCell(Module):
    def __init__(self, input_size, hidden_size, bias=True, device=None,
                 dtype="float32"):
        """
        An LSTM cell.

        Parameters:
            input_size: number of input features
            hidden_size: number of hidden features
            bias: whether to use bias

        Variables:
            W_ih: learnable input-hidden weights, shape (input_size, 4*hidden_size)
            W_hh: learnable hidden-hidden weights, shape (hidden_size, 4*hidden_size)
            bias_ih: learnable input-hidden bias, shape (4*hidden_size,)
            bias_hh: learnable hidden-hidden bias, shape (4*hidden_size,)

        Weights and biases are initialized from U(-sqrt(k), sqrt(k)) where
        k = 1/hidden_size.  Gate order: input, forget, cell, output (i, f, g, o).
        """
        super().__init__()
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def forward(self, X, h=None):
        """
        Args:
            X: (batch_size, input_size)
            h: optional tuple (h0, c0) each of shape (batch_size, hidden_size)
        Returns:
            (h', c') each of shape (batch_size, hidden_size)
        """
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class LSTM(Module):
    def __init__(self, input_size, hidden_size, num_layers=1, bias=True,
                 device=None, dtype="float32"):
        """
        Multi-layer LSTM.

        Parameters:
            input_size: number of input features
            hidden_size: number of hidden features
            num_layers: number of stacked LSTM layers
            bias: whether to use bias

        Variables:
            lstm_cells: list of LSTMCell modules, one per layer.
            Layer 0 has input_size input features; layers 1+ have hidden_size.
        """
        super().__init__()
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def forward(self, X, h=None):
        """
        Args:
            X: (seq_len, batch_size, input_size)
            h: optional tuple (h0, c0) with
                h0: (num_layers, batch_size, hidden_size)
                c0: (num_layers, batch_size, hidden_size)
        Returns:
            (output, (h_n, c_n))
            output: (seq_len, batch_size, hidden_size)
            h_n: (num_layers, batch_size, hidden_size)
            c_n: (num_layers, batch_size, hidden_size)
        """
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Embedding(Module):
    def __init__(self, num_embeddings, embedding_dim, device=None,
                 dtype="float32"):
        """
        Maps integer indices to dense embedding vectors.

        Parameters:
            num_embeddings: size of the dictionary
            embedding_dim: size of each embedding vector

        Variables:
            weight: (num_embeddings, embedding_dim) initialized from N(0,1)
        """
        super().__init__()
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def forward(self, x: Tensor) -> Tensor:
        """
        Args:
            x: (seq_len, batch_size) integer indices
        Returns:
            (seq_len, batch_size, embedding_dim) embedding vectors
        """
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION
