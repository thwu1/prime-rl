#!/usr/bin/env python3
"""
Write the complete C RoPE implementation and fix the Makefile.

"""

import sys
sys.path.insert(0, "/app")
from glm5_config import GLM5Config

config = GLM5Config()
print(f"RoPE head dim from config: {config.qk_rope_head_dim}")

# ── Write the C implementation ────────────────────────────────────────

c_code = r"""/*
 * Fused Rotary Position Embedding (RoPE) for GLM-5 MLA.
 *
 */

void rope_apply(const float* x, const float* cos_vals, const float* sin_vals,
                int dim, float* out) {
    int half = dim / 2;
    /*
     * PyTorch formula:
     *   rotate_half(x) = cat(-x[half:], x[:half])
     *   result = x * cos + rotate_half(x) * sin
     *
     * Element-wise:
     *   out[i]      = x[i] * cos[i]      - x[i+half] * sin[i]         (i < half)
     *   out[i+half] = x[i+half] * cos[i+half] + x[i] * sin[i+half]   (i < half)
     *
     * Reading x[i] and x[i+half] into locals before writing guarantees
     * correct results even when out aliases x (in-place operation).
     */
    for (int i = 0; i < half; i++) {
        float xi = x[i];
        float xh = x[i + half];
        out[i]        = xi * cos_vals[i]        - xh * sin_vals[i];
        out[i + half] = xh * cos_vals[i + half] + xi * sin_vals[i + half];
    }
}

void rope_apply_batch(const float* x, const float* cos_vals, const float* sin_vals,
                      int batch_size, int dim, float* out) {
    for (int b = 0; b < batch_size; b++) {
        int off = b * dim;
        rope_apply(x + off, cos_vals + off, sin_vals + off, dim, out + off);
    }
}
"""

with open("/app/csrc/rope_fused.c", "w") as f:
    f.write(c_code)
print("C RoPE implementation written to /app/csrc/rope_fused.c")

# ── Write the fixed Makefile ──────────────────────────────────────────

# Note: Makefile requires real tabs for recipe lines
makefile = "# Makefile for fused RoPE C extension\n"
makefile += "CC ?= gcc\n"
makefile += "CFLAGS = -O2 -fPIC -Wall\n"
makefile += "\n"
makefile += "SRCDIR = csrc\n"
makefile += "LIBDIR = lib\n"
makefile += "\n"
makefile += "build:\n"
makefile += "\tmkdir -p $(LIBDIR)\n"
makefile += "\t$(CC) -shared $(CFLAGS) $(SRCDIR)/rope_fused.c -o $(LIBDIR)/librope.so\n"
makefile += "\n"
makefile += "clean:\n"
makefile += "\trm -rf $(LIBDIR)\n"
makefile += "\n"
makefile += ".PHONY: build clean\n"

with open("/app/Makefile", "w") as f:
    f.write(makefile)
print("Makefile written to /app/Makefile")
