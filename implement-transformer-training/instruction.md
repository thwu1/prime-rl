`/app/transformer.py` contains a transformer encoder-decoder ported from a working reference implementation. The port introduced multiple silent defects in the model components that prevent training convergence. None produce runtime errors. The infrastructure code (training loop, data generation, batching, masking, greedy decoding) is correct and must not be modified.

**Expected**: A 2-layer model (d_model=64, d_ff=128, h=4, vocab=11) trained on a copy task for 40 epochs reaches loss < 0.5 and greedy decoding reproduces >= 7/10 input tokens.

**Observed**: Loss does not decrease meaningfully.

Find and fix all defects in the model components. Preserve the public API — class names, function names, constructor signatures, and method signatures must remain unchanged.