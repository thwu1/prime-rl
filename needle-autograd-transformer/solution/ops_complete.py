"""Complete implementations of all Needle operations."""

import numpy as np
from typing import Optional, Tuple, Union
from .autograd import TensorOp, Tensor


# ---------------------------------------------------------------------------
#  PROVIDED (working examples)
# ---------------------------------------------------------------------------

class EWiseAdd(TensorOp):
    def compute(self, a, b):
        return a + b

    def gradient(self, out_grad, node):
        return out_grad, out_grad


class AddScalar(TensorOp):
    def __init__(self, scalar):
        self.scalar = scalar

    def compute(self, a):
        return a + self.scalar

    def gradient(self, out_grad, node):
        return (out_grad,)


class EWiseMul(TensorOp):
    def compute(self, a, b):
        return a * b

    def gradient(self, out_grad, node):
        lhs, rhs = node.inputs
        return out_grad * rhs, out_grad * lhs


class MulScalar(TensorOp):
    def __init__(self, scalar):
        self.scalar = scalar

    def compute(self, a):
        return a * self.scalar

    def gradient(self, out_grad, node):
        return (out_grad * self.scalar,)


# ---------------------------------------------------------------------------
#  IMPLEMENTED
# ---------------------------------------------------------------------------

class PowerScalar(TensorOp):
    def __init__(self, scalar):
        self.scalar = scalar

    def compute(self, a):
        return a ** self.scalar

    def gradient(self, out_grad, node):
        a = node.inputs[0]
        return (out_grad * self.scalar * (a ** (self.scalar - 1)),)


class EWiseDiv(TensorOp):
    def compute(self, a, b):
        return a / b

    def gradient(self, out_grad, node):
        a, b = node.inputs
        return out_grad / b, -out_grad * a / (b * b)


class DivScalar(TensorOp):
    def __init__(self, scalar):
        self.scalar = scalar

    def compute(self, a):
        return a / self.scalar

    def gradient(self, out_grad, node):
        return (out_grad / self.scalar,)


class Transpose(TensorOp):
    def __init__(self, axes=None):
        self.axes = axes

    def compute(self, a):
        if self.axes is None:
            return np.swapaxes(a, -2, -1)
        return np.swapaxes(a, self.axes[0], self.axes[1])

    def gradient(self, out_grad, node):
        return (out_grad.transpose(self.axes),)


class Reshape(TensorOp):
    def __init__(self, shape):
        self.shape = shape

    def compute(self, a):
        return a.reshape(self.shape)

    def gradient(self, out_grad, node):
        return (out_grad.reshape(node.inputs[0].shape),)


class BroadcastTo(TensorOp):
    def __init__(self, shape):
        self.shape = shape

    def compute(self, a):
        return np.broadcast_to(a, self.shape)

    def gradient(self, out_grad, node):
        input_shape = node.inputs[0].shape
        output_shape = self.shape

        ndim_diff = len(output_shape) - len(input_shape)
        padded = (1,) * ndim_diff + input_shape

        axes = []
        for i in range(len(output_shape)):
            if padded[i] == 1 and output_shape[i] > 1:
                axes.append(i)

        if axes:
            grad = out_grad.sum(axes=tuple(axes))
        else:
            grad = out_grad
        return (grad.reshape(input_shape),)


class Summation(TensorOp):
    def __init__(self, axes=None):
        self.axes = axes

    def compute(self, a):
        return a.sum(axis=self.axes)

    def gradient(self, out_grad, node):
        input_shape = node.inputs[0].shape

        if self.axes is None:
            return (out_grad.broadcast_to(input_shape),)

        axes = self.axes if isinstance(self.axes, (tuple, list)) else (self.axes,)
        new_shape = list(input_shape)
        for ax in axes:
            new_shape[ax] = 1

        return (out_grad.reshape(tuple(new_shape)).broadcast_to(input_shape),)


class MatMul(TensorOp):
    def compute(self, a, b):
        return a @ b

    def gradient(self, out_grad, node):
        a, b = node.inputs
        grad_a = out_grad @ b.transpose()
        grad_b = a.transpose() @ out_grad

        if len(grad_a.shape) > len(a.shape):
            axes = tuple(range(len(grad_a.shape) - len(a.shape)))
            grad_a = grad_a.sum(axes=axes)
        if len(grad_b.shape) > len(b.shape):
            axes = tuple(range(len(grad_b.shape) - len(b.shape)))
            grad_b = grad_b.sum(axes=axes)

        return grad_a, grad_b


class Negate(TensorOp):
    def compute(self, a):
        return -a

    def gradient(self, out_grad, node):
        return (-out_grad,)


class Log(TensorOp):
    def compute(self, a):
        return np.log(a)

    def gradient(self, out_grad, node):
        return (out_grad / node.inputs[0],)


class Exp(TensorOp):
    def compute(self, a):
        return np.exp(a)

    def gradient(self, out_grad, node):
        return (out_grad * Tensor(node.realize_cached_data(), requires_grad=False),)


class ReLU(TensorOp):
    def compute(self, a):
        return np.maximum(a, 0)

    def gradient(self, out_grad, node):
        a_data = node.inputs[0].realize_cached_data()
        mask = Tensor((a_data > 0).astype(a_data.dtype), requires_grad=False)
        return (out_grad * mask,)


class Tanh(TensorOp):
    def compute(self, a):
        return np.tanh(a)

    def gradient(self, out_grad, node):
        tanh_val = node.realize_cached_data()
        return (out_grad * Tensor(1 - tanh_val ** 2, requires_grad=False),)
