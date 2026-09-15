
"""Operation types for gradient rematerialization schedules.

Each operation models one step in a training schedule for a sequential neural
network.  The operations modify a memory state that tracks which activations
and gradients are currently stored.

Memory items and their sizes (from chain attributes):
    x_i   : activation at position i, stored WITHOUT gradient tracking.
             Size = chain.cweigth[i].
    xbar_i: activation at position i, stored WITH gradient tracking.
             Size = chain.cbweigth[i].
    y_i   : gradient at position i.
             Size = chain.cweigth[i].

Operation semantics (memory effects):
    ForwardCheck(i):
        Precondition: x_i or xbar_i is in memory.
        Effect: adds x_{i+1} to memory. Input is RETAINED (checkpointed).
        Peak memory during operation: all stored items + fwd_tmp[i].
        Computation time: fweigth[i].

    ForwardNograd(i):
        Precondition: x_i or xbar_i is in memory.
        Effect: adds x_{i+1} and REMOVES x_i/xbar_i (input is discarded).
        Peak memory during operation: all stored items (including both input
        and output, before input removal) + fwd_tmp[i].
        Computation time: fweigth[i].

    ForwardEnable(i):
        Precondition: x_i or xbar_i is in memory.
        Effect: adds xbar_{i+1} to memory. Input is RETAINED.
        Peak memory during operation: all stored items + fwd_tmp[i].
        Computation time: fweigth[i].

    Loss():
        Precondition: x_n or xbar_n is in memory (n = chain.length).
        Effect: adds y_n to memory.
        Peak memory during operation: all stored items + bwd_tmp[n].
        Computation time: 0.

    Backward(i):
        Precondition: xbar_{i+1} AND y_{i+1} are both in memory.
        Effect: adds y_i to memory, then removes x_i if present (but NOT
        xbar_i), then removes y_{i+1} and xbar_{i+1}.
        Peak memory during operation: all stored items (after adding y_i,
        before any removals) + bwd_tmp[i].
        Computation time: bweigth[i].
"""


class Operation:
    """Base class for schedule operations."""
    pass


class Forward(Operation):
    """Base class for forward operations."""

    def __init__(self, index):
        self.index = index

    def __repr__(self):
        return f"{self.__class__.__name__}({self.index})"

    def __eq__(self, other):
        return type(self) is type(other) and self.index == other.index


class ForwardCheck(Forward):
    """Forward pass without gradient; checkpoint (retain) input activation."""
    pass


class ForwardNograd(Forward):
    """Forward pass without gradient; discard input activation."""
    pass


class ForwardEnable(Forward):
    """Forward pass with gradient tracking; retain input activation."""
    pass


class Backward(Operation):
    """Backward pass for layer i."""

    def __init__(self, index):
        self.index = index

    def __repr__(self):
        return f"Backward({self.index})"

    def __eq__(self, other):
        return type(self) is type(other) and self.index == other.index


class Loss(Operation):
    """Loss computation at the end of the chain."""

    def __repr__(self):
        return "Loss()"

    def __eq__(self, other):
        return type(self) is type(other)
