#!/usr/bin/env python3
"""
Fix the five defects in /app/transformer.py:
1. attention() missing score normalization by sqrt(d_k)
2. PositionalEncoding uses sin for both even and odd dimensions (odd should use cos)
3. SublayerConnection uses post-norm (norm after residual sum) instead of pre-norm
4. Embeddings.forward() missing scaling by sqrt(d_model)
5. make_model() missing xavier_uniform_ parameter initialization
"""

import re

with open("/app/transformer.py", "r") as f:
    code = f.read()

# Fix 1: Add sqrt(d_k) scaling in attention
code = code.replace(
    "    scores = torch.matmul(query, key.transpose(-2, -1))\n",
    "    scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(d_k)\n",
)

# Fix 2: Use cos for odd-indexed PE dimensions
code = code.replace(
    "        pe[:, 1::2] = torch.sin(position * div_term)\n",
    "        pe[:, 1::2] = torch.cos(position * div_term)\n",
)

# Fix 3: Change SublayerConnection from post-norm to pre-norm
code = code.replace(
    "        return self.norm(x + self.dropout(sublayer(x)))\n",
    "        return x + self.dropout(sublayer(self.norm(x)))\n",
)

# Fix 4: Scale embedding output by sqrt(d_model)
code = code.replace(
    "        return self.lut(x)\n",
    "        return self.lut(x) * math.sqrt(self.d_model)\n",
)

# Fix 5: Add xavier_uniform_ initialization in make_model
code = code.replace(
    "    return model\n",
    "    for p in model.parameters():\n"
    "        if p.dim() > 1:\n"
    "            nn.init.xavier_uniform_(p)\n"
    "    return model\n",
)

with open("/app/transformer.py", "w") as f:
    f.write(code)

# Verify the fixes load and a forward pass works
import importlib.util
import torch

spec = importlib.util.spec_from_file_location("transformer", "/app/transformer.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

model = mod.make_model(11, 11, N=2, d_model=64, d_ff=128, h=4, dropout=0.0)
model.eval()
src = torch.LongTensor([[1, 2, 3, 4, 5]])
tgt = torch.LongTensor([[1, 2, 3, 4]])
src_mask = torch.ones(1, 1, 5)
tgt_mask = mod.subsequent_mask(4)
out = model(src, tgt, src_mask, tgt_mask)
assert out.shape == (1, 4, 64), f"Unexpected shape {out.shape}"
print(f"All fixes applied. Forward pass verified: {out.shape}")
