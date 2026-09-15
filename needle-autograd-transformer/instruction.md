You are given a minimal deep learning framework at `/app/needle/` with NumPy backend. The reverse-mode automatic differentiation engine is complete (`autograd.py`). Two operations (EWiseAdd, EWiseMul) and their scalar variants are provided as working examples.

Implement all operations marked `raise NotImplementedError()` in `/app/needle/ops.py` (13 operations, each requiring both forward `compute` and backward `gradient` method) and all modules in `/app/needle/nn.py` (8 modules including multi-head causal self-attention and a pre-norm transformer encoder layer).

Every backward pass is verified via numerical gradient checking (finite differences).

Key files:
- `/app/needle/autograd.py` — Autograd engine (complete, do not modify)
- `/app/needle/ops.py` — Operations to implement
- `/app/needle/nn.py` — Neural network modules to implement
- `/app/needle/init.py` — Initialization utilities (complete, do not modify)

If framework files are missing from `/app/needle/`, restore them from `/opt/needle-src/`.