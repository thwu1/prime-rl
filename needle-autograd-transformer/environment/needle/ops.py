"""Operations for the Needle framework.

EWiseAdd, AddScalar, EWiseMul, and MulScalar are provided as working examples.
Implement all other operations marked with ``raise NotImplementedError()``.
Each operation needs both ``compute`` (forward) and ``gradient`` (backward).
"""

import numpy as np
from typing import Optional, Tuple, Union
from .autograd import TensorOp, Tensor


# ---------------------------------------------------------------------------
#  PROVIDED (working examples)
# ---------------------------------------------------------------------------

class EWiseAdd(TensorOp):
    """Element-wise addition of two tensors."""

    def compute(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a + b

    def gradient(self, out_grad: Tensor, node: Tensor):
        return out_grad, out_grad


class AddScalar(TensorOp):
    """Add a scalar to every element of a tensor."""

    def __init__(self, scalar):
        self.scalar = scalar

    def compute(self, a: np.ndarray) -> np.ndarray:
        return a + self.scalar

    def gradient(self, out_grad: Tensor, node: Tensor):
        return (out_grad,)


class EWiseMul(TensorOp):
    """Element-wise multiplication of two tensors."""

    def compute(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a * b

    def gradient(self, out_grad: Tensor, node: Tensor):
        lhs, rhs = node.inputs
        return out_grad * rhs, out_grad * lhs


class MulScalar(TensorOp):
    """Multiply every element of a tensor by a scalar."""

    def __init__(self, scalar):
        self.scalar = scalar

    def compute(self, a: np.ndarray) -> np.ndarray:
        return a * self.scalar

    def gradient(self, out_grad: Tensor, node: Tensor):
        return (out_grad * self.scalar,)


# ---------------------------------------------------------------------------
#  TO IMPLEMENT
# ---------------------------------------------------------------------------

class PowerScalar(TensorOp):
    """Raise a tensor to a scalar power (integer or float)."""

    def __init__(self, scalar):
        self.scalar = scalar

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class EWiseDiv(TensorOp):
    """Element-wise division: a / b."""

    def compute(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class DivScalar(TensorOp):
    """Divide every element of a tensor by a scalar."""

    def __init__(self, scalar):
        self.scalar = scalar

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Transpose(TensorOp):
    """Swap two axes of a tensor.

    If axes is None, swap the last two axes.
    Otherwise axes is a tuple (ax0, ax1) specifying which two axes to swap.
    """

    def __init__(self, axes: Optional[tuple] = None):
        self.axes = axes

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Reshape(TensorOp):
    """Reshape a tensor to a new shape (total number of elements unchanged)."""

    def __init__(self, shape):
        self.shape = shape

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class BroadcastTo(TensorOp):
    """Broadcast a tensor to a target shape.

    Follows NumPy broadcasting rules: dimensions are aligned from the right,
    and size-1 dimensions (or missing leading dimensions) are expanded.
    """

    def __init__(self, shape):
        self.shape = shape

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Summation(TensorOp):
    """Sum elements of a tensor along specified axes.

    axes can be None (sum all), an int, or a tuple of ints.
    Summed dimensions are removed (not kept as size-1).
    """

    def __init__(self, axes=None):
        self.axes = axes

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class MatMul(TensorOp):
    """Matrix multiplication with broadcasting support for batch dimensions.

    For 2-D inputs this is standard matrix multiply.
    For higher-dimensional inputs, the last two dimensions are the matrix
    dimensions and leading dimensions are broadcast batch dimensions
    (following numpy.matmul semantics).
    """

    def compute(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Negate(TensorOp):
    """Element-wise negation."""

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Log(TensorOp):
    """Element-wise natural logarithm."""

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Exp(TensorOp):
    """Element-wise exponential."""

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class ReLU(TensorOp):
    """Element-wise rectified linear unit: max(0, x)."""

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION


class Tanh(TensorOp):
    """Element-wise hyperbolic tangent."""

    def compute(self, a: np.ndarray) -> np.ndarray:
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def gradient(self, out_grad: Tensor, node: Tensor):
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION
