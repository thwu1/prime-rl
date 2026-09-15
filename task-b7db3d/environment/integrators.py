"""DFG integrators using different importance sampling strategies.

All integrators compute the split-sum DFG integral by sampling the
half-vector H, reflecting V around H to get L, and accumulating
weighted contributions using the BRDF functions from ffi_bridge.

V is always (sqrt(1 - NoV^2), 0, NoV) in tangent space.
H is sampled, then L = 2*(V.H)*H - V.
Only samples where NoL > 0 and NoH > 0 contribute.

For each valid sample:
  VoH = clamp(dot(V, H), 0, inf)
  NoL = clamp(L.z, 0, inf)
  NoH = clamp(H.z, 0, inf)
  Fc = (1 - VoH)^5
  DFG.x += weight * (1 - Fc)
  DFG.y += weight * Fc

Weight formulas per strategy (see spec.md for derivations):
  GGX IS:   w = V_SmithGGX(NoV, NoL, alpha) * 4 * VoH * NoL / NoH
  Cosine:   w = D_GGX(NoH, alpha) * V_SmithGGX(NoV, NoL, alpha) * 4 * VoH * NoL * pi / NoH
  Uniform:  w = D_GGX(NoH, alpha) * V_SmithGGX(NoV, NoL, alpha) * 4 * VoH * NoL * 2*pi

Cloth uses Charlie IS with Neubelt visibility (single scalar output):
  w = V_Neubelt(NoV, NoL) * 4 * VoH * NoL / NoH

alpha = roughness^2 (perceptual to linear remapping)
Hammersley sequence: (i/N, hammersley_ri(i))
"""
import math


def integrate_dfg_ggx_is(NoV, roughness, num_samples=1024):
    """Compute DFG using GGX importance sampling. Returns (dfg_x, dfg_y)."""
    raise NotImplementedError

def integrate_dfg_cosine(NoV, roughness, num_samples=1024):
    """Compute DFG using cosine-weighted hemisphere sampling. Returns (dfg_x, dfg_y)."""
    raise NotImplementedError

def integrate_dfg_uniform(NoV, roughness, num_samples=1024):
    """Compute DFG using uniform hemisphere sampling. Returns (dfg_x, dfg_y)."""
    raise NotImplementedError

def integrate_dfg_cloth(NoV, roughness, num_samples=1024):
    """Compute cloth DFG using Charlie IS + Neubelt visibility. Returns float."""
    raise NotImplementedError
