"""Numpy-based CPU device backend."""
import numpy


class Device:
    """Base class of all devices."""


class CPUDevice(Device):
    def __repr__(self):
        return "needle.cpu()"

    def __hash__(self):
        return self.__repr__().__hash__()

    def __eq__(self, other):
        return isinstance(other, CPUDevice)

    def enabled(self):
        return True

    def zeros(self, *shape, dtype="float32"):
        return numpy.zeros(shape, dtype=dtype)

    def ones(self, *shape, dtype="float32"):
        return numpy.ones(shape, dtype=dtype)

    def randn(self, *shape):
        return numpy.random.randn(*shape)

    def rand(self, *shape):
        return numpy.random.rand(*shape)

    def one_hot(self, n, i, dtype="float32"):
        return numpy.eye(n, dtype=dtype)[i]

    def empty(self, shape, dtype="float32"):
        return numpy.empty(shape, dtype=dtype)

    def full(self, shape, fill_value, dtype="float32"):
        return numpy.full(shape, fill_value, dtype=dtype)


def cpu():
    return CPUDevice()


def default_device():
    return cpu()


def all_devices():
    return [cpu()]
