The encoder-decoder model at `/app/model.py` and training script `/app/train.py` depend on primitive operations defined in `/app/ops.py`. Every function body in that module currently raises `NotImplementedError`.

Study the model architecture and training code to determine the exact mathematical specification of each operation, then provide working implementations. The model uses several non-standard design choices — standard textbook implementations will not work. Do not modify `model.py` or `train.py`.

**Constraints:**
- Implementations must use only basic PyTorch tensor operations — do not import `torch.nn` or `torch.nn.functional` in `ops.py`
- When `python3 /app/train.py` completes, it writes `/app/results.json`
- `final_loss` must be < 0.5
- `copy_accuracy` must be >= 0.85