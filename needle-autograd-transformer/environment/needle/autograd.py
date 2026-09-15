"""Autograd engine for the Needle deep learning framework.

Implements computational graph, tensor class, and reverse-mode automatic
differentiation. This module is complete and should not be modified.
"""

import numpy as np
from typing import List, Optional, Tuple, Union, Dict


class Op:
    """Base class for all operations."""

    def __call__(self, *args):
        raise NotImplementedError()

    def compute(self, *args: Tuple[np.ndarray]) -> np.ndarray:
        """Forward pass: compute output from numpy array inputs."""
        raise NotImplementedError()

    def gradient(
        self, out_grad: "Value", node: "Value"
    ) -> Union["Value", Tuple["Value"]]:
        """Backward pass: compute gradient w.r.t. each input."""
        raise NotImplementedError()

    def gradient_as_tuple(
        self, out_grad: "Value", node: "Value"
    ) -> Tuple["Value"]:
        output = self.gradient(out_grad, node)
        if isinstance(output, tuple):
            return output
        elif isinstance(output, list):
            return tuple(output)
        else:
            return (output,)


class TensorOp(Op):
    """Op that produces a Tensor output."""

    def __call__(self, *args):
        return Tensor.make_from_op(self, args)


class Value:
    """A value in the computational graph."""

    op: Optional[Op]
    inputs: List["Value"]
    cached_data: np.ndarray
    requires_grad: bool

    def realize_cached_data(self):
        if self.cached_data is not None:
            return self.cached_data
        self.cached_data = self.op.compute(
            *[x.realize_cached_data() for x in self.inputs]
        )
        return self.cached_data

    def is_leaf(self):
        return self.op is None

    def _init(self, op, inputs, *, cached_data=None, requires_grad=None):
        if requires_grad is None:
            requires_grad = any(x.requires_grad for x in inputs)
        self.op = op
        self.inputs = inputs
        self.cached_data = cached_data
        self.requires_grad = requires_grad

    @classmethod
    def make_const(cls, data, *, requires_grad=False):
        value = cls.__new__(cls)
        value._init(None, [], cached_data=data, requires_grad=requires_grad)
        return value

    @classmethod
    def make_from_op(cls, op, inputs):
        value = cls.__new__(cls)
        value._init(op, inputs)
        if not value.requires_grad:
            return value.detach()
        value.realize_cached_data()
        return value


class Tensor(Value):
    """Multi-dimensional array with automatic differentiation support."""

    grad: "Tensor"

    def __init__(self, array, *, dtype=None, requires_grad=True):
        if isinstance(array, Tensor):
            cached_data = array.realize_cached_data().copy()
        elif isinstance(array, np.ndarray):
            cached_data = array.astype(dtype) if dtype is not None else array.copy()
        else:
            cached_data = np.array(array, dtype=dtype or "float32")
        self._init(None, [], cached_data=cached_data, requires_grad=requires_grad)

    @staticmethod
    def make_from_op(op, inputs):
        tensor = Tensor.__new__(Tensor)
        tensor._init(op, inputs)
        if not tensor.requires_grad:
            return tensor.detach()
        tensor.realize_cached_data()
        return tensor

    @staticmethod
    def make_const(data, requires_grad=False):
        tensor = Tensor.__new__(Tensor)
        if isinstance(data, Tensor):
            data = data.realize_cached_data()
        tensor._init(None, [], cached_data=data, requires_grad=requires_grad)
        return tensor

    @property
    def data(self):
        return self.detach()

    @data.setter
    def data(self, value):
        assert isinstance(value, Tensor)
        self.cached_data = value.realize_cached_data()

    def detach(self):
        return Tensor.make_const(self.realize_cached_data())

    @property
    def shape(self):
        return self.realize_cached_data().shape

    @property
    def dtype(self):
        return self.realize_cached_data().dtype

    def numpy(self):
        return np.array(self.realize_cached_data())

    def backward(self, out_grad=None):
        if out_grad is None:
            out_grad = Tensor(
                np.ones(self.shape, dtype=self.dtype), requires_grad=False
            )
        compute_gradient_of_variables(self, out_grad)

    def __repr__(self):
        return "Tensor(" + str(self.realize_cached_data()) + ")"

    def __str__(self):
        return str(self.realize_cached_data())

    # ---- arithmetic operators ----

    def __add__(self, other):
        from . import ops
        if isinstance(other, Tensor):
            return ops.EWiseAdd()(self, other)
        return ops.AddScalar(other)(self)

    __radd__ = __add__

    def __mul__(self, other):
        from . import ops
        if isinstance(other, Tensor):
            return ops.EWiseMul()(self, other)
        return ops.MulScalar(other)(self)

    __rmul__ = __mul__

    def __pow__(self, scalar):
        from . import ops
        return ops.PowerScalar(scalar)(self)

    def __sub__(self, other):
        from . import ops
        if isinstance(other, Tensor):
            return ops.EWiseAdd()(self, ops.Negate()(other))
        return ops.AddScalar(-other)(self)

    def __rsub__(self, other):
        from . import ops
        return ops.AddScalar(other)(ops.Negate()(self))

    def __truediv__(self, other):
        from . import ops
        if isinstance(other, Tensor):
            return ops.EWiseDiv()(self, other)
        return ops.DivScalar(other)(self)

    def __neg__(self):
        from . import ops
        return ops.Negate()(self)

    def __matmul__(self, other):
        from . import ops
        return ops.MatMul()(self, other)

    # ---- tensor methods ----

    def sum(self, axes=None):
        from . import ops
        return ops.Summation(axes)(self)

    def broadcast_to(self, shape):
        from . import ops
        return ops.BroadcastTo(shape)(self)

    def reshape(self, shape):
        from . import ops
        return ops.Reshape(shape)(self)

    def transpose(self, axes=None):
        from . import ops
        return ops.Transpose(axes)(self)

    def tanh(self):
        from . import ops
        return ops.Tanh()(self)

    def exp(self):
        from . import ops
        return ops.Exp()(self)

    def log(self):
        from . import ops
        return ops.Log()(self)

    def relu(self):
        from . import ops
        return ops.ReLU()(self)


def find_topo_sort(node_list: List[Value]) -> List[Value]:
    """Topological sort via post-order DFS."""
    visited = set()
    topo_order = []
    for node in node_list:
        _topo_sort_dfs(node, visited, topo_order)
    return topo_order


def _topo_sort_dfs(node: Value, visited: set, topo_order: list):
    if id(node) in visited:
        return
    visited.add(id(node))
    for inp in node.inputs:
        _topo_sort_dfs(inp, visited, topo_order)
    topo_order.append(node)


def compute_gradient_of_variables(output_tensor: Tensor, out_grad: Tensor):
    """Reverse-mode automatic differentiation.

    Traverse the computational graph in reverse topological order,
    accumulating gradients via the chain rule.
    """
    node_to_output_grads_list: Dict[int, List[Tensor]] = {}
    node_to_output_grads_list[id(output_tensor)] = [out_grad]

    reverse_topo_order = list(reversed(find_topo_sort([output_tensor])))

    for node in reverse_topo_order:
        node_id = id(node)
        if node_id not in node_to_output_grads_list:
            continue

        grad_list = node_to_output_grads_list[node_id]
        if len(grad_list) == 1:
            adjoint = grad_list[0]
        else:
            adjoint = grad_list[0]
            for g in grad_list[1:]:
                adjoint = adjoint + g

        if node.is_leaf():
            node.grad = adjoint
        else:
            input_grads = node.op.gradient_as_tuple(adjoint, node)
            for i, inp in enumerate(node.inputs):
                inp_id = id(inp)
                if inp_id not in node_to_output_grads_list:
                    node_to_output_grads_list[inp_id] = []
                node_to_output_grads_list[inp_id].append(input_grads[i])
