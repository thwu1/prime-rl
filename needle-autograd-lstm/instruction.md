The `/app/` directory contains **Needle**, an incomplete deep learning framework with a numpy-based backend. Some infrastructure already works — the `Tensor` class, device abstraction, basic element-wise arithmetic ops (add, multiply, divide, negate, power, relu), and `stack`/`split` — but numerous core components across the automatic differentiation engine, tensor operations, neural network modules, optimizer, and application layer are stubbed out with `raise NotImplementedError()`.

Complete **all** unfinished implementations so that the framework can train an LSTM-based language model end-to-end with gradient-based optimization. Every stub is marked with `### BEGIN YOUR SOLUTION` / `### END YOUR SOLUTION` blocks.

The framework has its own conventions for tensor layout, weight shapes, initialization, and op interfaces that differ from other frameworks in subtle but correctness-critical ways. Study the existing working code, class hierarchies, docstrings, type annotations, and initialization utilities in `/app/needle/init.py` carefully — the conventions must be followed exactly.

Success is measured by the test suite at `/tests/test_state.py`.