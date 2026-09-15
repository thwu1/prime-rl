#!/usr/bin/env python3

"""
Export the MLAWithDSA module via torch.jit.trace and generate a
torch.profiler Chrome trace.
"""

import torch
import torch.nn as nn
import sys

sys.path.insert(0, "/app")

from mla_dsa_attention import MLAWithDSA
from config import CONFIG
from utils import compute_rope_embeddings, make_causal_mask


def main():
    # Initialize module
    torch.manual_seed(0)
    module = MLAWithDSA(CONFIG, layer_idx=0)
    module.eval()

    # Create example inputs
    B, S = 2, 16
    hidden = torch.randn(B, S, CONFIG["hidden_size"])
    pos_ids = torch.arange(S).unsqueeze(0).expand(B, -1)
    cos, sin = compute_rope_embeddings(pos_ids, CONFIG)
    mask = make_causal_mask(S, 0, hidden.dtype, hidden.device)

    # --- TorchScript trace export ---
    # Wrap module for clean trace (prefill path only, no optional args)
    class PrefillWrapper(nn.Module):
        def __init__(self, mla_module):
            super().__init__()
            self.mla = mla_module

        def forward(self, hidden_states, position_ids, cos, sin, attention_mask):
            output, _ = self.mla(
                hidden_states, position_ids, cos, sin,
                attention_mask=attention_mask,
            )
            return output

    wrapper = PrefillWrapper(module)
    wrapper.eval()

    with torch.no_grad():
        traced = torch.jit.trace(wrapper, (hidden, pos_ids, cos, sin, mask))
    traced.save("/app/mla_dsa_traced.pt")
    print("Saved traced model to /app/mla_dsa_traced.pt")

    # --- torch.profiler Chrome trace ---
    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU],
        record_shapes=True,
    ) as prof:
        with torch.no_grad():
            for _ in range(3):
                module(hidden, pos_ids, cos, sin, attention_mask=mask)

    prof.export_chrome_trace("/app/profile_trace.json")
    print("Saved profile trace to /app/profile_trace.json")


if __name__ == "__main__":
    main()
