The file `/app/transformer.py` contains stubs for a Transformer language model and associated training utilities. Every function and class body raises `NotImplementedError`.

Implement all stubs in `/app/transformer.py` so that the complete test suite at `/tests/test_state.py` passes. The tests validate each component in isolation and as an integrated training pipeline.

Constraints:
- All implementations must reside in `/app/transformer.py`.
- You may only use `torch.nn.Parameter`, `torch.nn.Module`, `torch.nn.ModuleList`, and `torch.optim.Optimizer` (base class) from `torch.nn`/`torch.optim`.
- Do not import or use `torch.nn.functional`, `torch.nn.Linear`, `torch.nn.Embedding`, `torch.nn.LayerNorm`, or any pre-built optimizer.