"""Core data structures for automatic differentiation."""
import numpy
from typing import List, Optional, Tuple, Union, Dict
from .backend_numpy import Device, cpu, all_devices

import numpy as array_api
NDArray = numpy.ndarray

LAZY_MODE = False
TENSOR_COUNTER = 0


class Op:
    """Operator definition."""

    def __call__(self, *args):
        raise NotImplementedError()

    def compute(self, *args: Tuple[NDArray]):
        raise NotImplementedError()

    def gradient(self, out_grad: "Value", node: "Value") -> Union["Value", Tuple["Value"]]:
        raise NotImplementedError()

    def gradient_as_tuple(self, out_grad: "Value", node: "Value") -> Tuple["Value"]:
        output = self.gradient(out_grad, node)
        if isinstance(output, tuple):
            return output
        elif isinstance(output, list):
            return tuple(output)
        else:
            return (output,)


class TensorOp(Op):
    """Op class specialized to output tensors."""

    def __call__(self, *args):
        return Tensor.make_from_op(self, args)


class TensorTupleOp(Op):
    """Op class specialized to output TensorTuple."""

    def __call__(self, *args):
        return TensorTuple.make_from_op(self, args)


class Value:
    """A value in the computational graph."""

    op: Optional[Op]
    inputs: List["Value"]
    cached_data: NDArray
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

    def __del__(self):
        global TENSOR_COUNTER
        TENSOR_COUNTER -= 1

    def _init(self, op, inputs, *, num_outputs=1, cached_data=None, requires_grad=None):
        global TENSOR_COUNTER
        TENSOR_COUNTER += 1
        if requires_grad is None:
            requires_grad = any(x.requires_grad for x in inputs)
        self.op = op
        self.inputs = inputs
        self.num_outputs = num_outputs
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
        if not LAZY_MODE:
            if not value.requires_grad:
                return value.detach()
            value.realize_cached_data()
        return value


class TensorTuple(Value):
    """Represent a tuple of tensors."""

    def __len__(self):
        cdata = self.realize_cached_data()
        return len(cdata)

    def __getitem__(self, index: int):
        import needle.ops as ops_module
        return ops_module.tuple_get_item(self, index)

    def tuple(self):
        return tuple([x for x in self])

    def __repr__(self):
        return "needle.TensorTuple" + str(self.tuple())

    def __str__(self):
        return self.__repr__()

    def __add__(self, other):
        assert isinstance(other, TensorTuple)
        assert len(self) == len(other)
        import needle.ops as ops_module
        return ops_module.make_tuple(*[self[i] + other[i] for i in range(len(self))])

    def detach(self):
        return TensorTuple.make_const(self.realize_cached_data())


class Tensor(Value):
    grad: "Tensor"

    def __init__(self, array, *, device=None, dtype=None, requires_grad=True, **kwargs):
        if isinstance(array, Tensor):
            if device is None:
                device = array.device
            if dtype is None:
                dtype = array.dtype
            cached_data = array.realize_cached_data()
        else:
            device = device if device else cpu()
            cached_data = numpy.array(array, dtype=dtype if dtype else "float32")
        self._init(None, [], cached_data=cached_data, requires_grad=requires_grad)

    @staticmethod
    def make_from_op(op, inputs):
        tensor = Tensor.__new__(Tensor)
        tensor._init(op, inputs)
        if not LAZY_MODE:
            if not tensor.requires_grad:
                return tensor.detach()
            tensor.realize_cached_data()
        return tensor

    @staticmethod
    def make_const(data, requires_grad=False):
        tensor = Tensor.__new__(Tensor)
        tensor._init(
            None, [],
            cached_data=data if not isinstance(data, Tensor) else data.realize_cached_data(),
            requires_grad=requires_grad,
        )
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

    @property
    def device(self):
        return cpu()

    def backward(self, out_grad=None):
        from . import init
        out_grad = (
            out_grad if out_grad
            else init.ones(*self.shape, dtype=self.dtype, device=self.device)
        )
        compute_gradient_of_variables(self, out_grad)

    def __repr__(self):
        return "needle.Tensor(" + str(self.realize_cached_data()) + ")"

    def __str__(self):
        return self.realize_cached_data().__str__()

    def numpy(self):
        return self.realize_cached_data()

    def __add__(self, other):
        import needle.ops as ops_module
        if isinstance(other, Tensor):
            return ops_module.EWiseAdd()(self, other)
        else:
            return ops_module.AddScalar(other)(self)

    def __mul__(self, other):
        import needle.ops as ops_module
        if isinstance(other, Tensor):
            return ops_module.EWiseMul()(self, other)
        else:
            return ops_module.MulScalar(other)(self)

    def __pow__(self, other):
        import needle.ops as ops_module
        if isinstance(other, Tensor):
            raise NotImplementedError("element-wise power between tensors")
        else:
            return ops_module.PowerScalar(other)(self)

    def __sub__(self, other):
        import needle.ops as ops_module
        if isinstance(other, Tensor):
            return ops_module.EWiseAdd()(self, ops_module.Negate()(other))
        else:
            return ops_module.AddScalar(-other)(self)

    def __truediv__(self, other):
        import needle.ops as ops_module
        if isinstance(other, Tensor):
            return ops_module.EWiseDiv()(self, other)
        else:
            return ops_module.DivScalar(other)(self)

    def __matmul__(self, other):
        import needle.ops as ops_module
        return ops_module.MatMul()(self, other)

    def matmul(self, other):
        import needle.ops as ops_module
        return ops_module.MatMul()(self, other)

    def sum(self, axes=None):
        import needle.ops as ops_module
        return ops_module.Summation(axes)(self)

    def broadcast_to(self, shape):
        import needle.ops as ops_module
        return ops_module.BroadcastTo(shape)(self)

    def reshape(self, shape):
        import needle.ops as ops_module
        return ops_module.Reshape(shape)(self)

    def __neg__(self):
        import needle.ops as ops_module
        return ops_module.Negate()(self)

    def transpose(self, axes=None):
        import needle.ops as ops_module
        return ops_module.Transpose(axes)(self)

    def __rsub__(self, other):
        import needle.ops as ops_module
        # other - self
        return ops_module.AddScalar(other)(ops_module.Negate()(self))

    def __rtruediv__(self, other):
        import needle.ops as ops_module
        # other / self
        return ops_module.MulScalar(other)(ops_module.PowerScalar(-1)(self))

    __radd__ = __add__
    __rmul__ = __mul__


def compute_gradient_of_variables(output_tensor, out_grad):
    """Take gradient of output node with respect to each node in node_list.

    Store the computed result in the grad field of each Variable.
    """
    node_to_output_grads_list: Dict[Tensor, List[Tensor]] = {}
    node_to_output_grads_list[output_tensor] = [out_grad]

    reverse_topo_order = list(reversed(find_topo_sort([output_tensor])))

    ### BEGIN YOUR SOLUTION
    raise NotImplementedError()
    ### END YOUR SOLUTION


def find_topo_sort(node_list: List[Value]) -> List[Value]:
    """Given a list of nodes, return a topological sort list of nodes ending in them.

    A simple algorithm is to do a post-order DFS traversal on the given nodes,
    going backwards based on input edges. Since a node is added to the ordering
    after all its predecessors are traversed due to post-order DFS, we get a
    topological sort.
    """
    ### BEGIN YOUR SOLUTION
    raise NotImplementedError()
    ### END YOUR SOLUTION


def topo_sort_dfs(node, visited, topo_order):
    """Post-order DFS."""
    ### BEGIN YOUR SOLUTION
    raise NotImplementedError()
    ### END YOUR SOLUTION


def sum_node_list(node_list):
    """Custom sum function in order to avoid create redundant nodes in Python sum implementation."""
    from operator import add
    from functools import reduce
    return reduce(add, node_list)
