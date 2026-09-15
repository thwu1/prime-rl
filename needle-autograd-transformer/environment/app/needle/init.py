"""Initialization utilities for the Needle framework."""

import numpy as np
from .autograd import Tensor


def ones(*shape, dtype="float32", requires_grad=True):
    return Tensor(np.ones(shape, dtype=dtype), requires_grad=requires_grad)


def zeros(*shape, dtype="float32", requires_grad=True):
    return Tensor(np.zeros(shape, dtype=dtype), requires_grad=requires_grad)


def randn(*shape, dtype="float32", requires_grad=True):
    return Tensor(np.random.randn(*shape).astype(dtype), requires_grad=requires_grad)


def kaiming_uniform(fan_in, fan_out, dtype="float32", requires_grad=True):
    bound = (6.0 / fan_in) ** 0.5
    arr = np.random.uniform(-bound, bound, (fan_in, fan_out)).astype(dtype)
    return Tensor(arr, requires_grad=requires_grad)


def uniform(low, high, shape, dtype="float32", requires_grad=True):
    arr = np.random.uniform(low, high, shape).astype(dtype)
    return Tensor(arr, requires_grad=requires_grad)
