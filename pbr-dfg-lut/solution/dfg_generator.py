#!/usr/bin/env python3

"""
DFG LUT Generator for PBR Image-Based Lighting.

Generates a 128x128 three-channel lookup table pre-integrating the Cook-Torrance
specular BRDF (multiscatter variant) and cloth sheen BRDF for the split-sum
approximation used in real-time IBL.

Channels:
  R = DFG1_multiscatter (Fc-weighted component)
  G = DFG2_multiscatter (total component)
  B = DFG_Charlie       (cloth sheen directional albedo)
"""

import math
import struct
import os

# --- Constants ---
PI = math.pi
INV_PI = 1.0 / PI
LUT_SIZE = 128
GGX_SAMPLES = 1024
CHARLIE_SAMPLES = 4096


# --- Utility ---
def saturate(x):
    return max(0.0, min(1.0, x))


def pow5(x):
    x2 = x * x
    return x2 * x2 * x


# --- Hammersley Sequence ---
def radical_inverse(bits):
    """Van der Corput radical inverse in base 2 using bit manipulation."""
    bits = int(bits) & 0xFFFFFFFF
    bits = ((bits << 16) | (bits >> 16)) & 0xFFFFFFFF
    bits = (((bits & 0x55555555) << 1) | ((bits & 0xAAAAAAAA) >> 1)) & 0xFFFFFFFF
    bits = (((bits & 0x33333333) << 2) | ((bits & 0xCCCCCCCC) >> 2)) & 0xFFFFFFFF
    bits = (((bits & 0x0F0F0F0F) << 4) | ((bits & 0xF0F0F0F0) >> 4)) & 0xFFFFFFFF
    bits = (((bits & 0x00FF00FF) << 8) | ((bits & 0xFF00FF00) >> 8)) & 0xFFFFFFFF
    return bits * 2.3283064365386963e-10


def hammersley(i, inv_n):
    """Return the i-th 2D Hammersley point."""
    return (i * inv_n, radical_inverse(i))


# --- GGX Importance Sampling ---
def importance_sample_ggx(u, a):
    """
    Sample a half-vector H from the GGX distribution in tangent space.
    a = linear roughness (alpha).
    Returns H = (x, y, z) with z = cos(theta).
    """
    phi = 2.0 * PI * u[0]
    # Using (a+1)(a-1) = a^2-1 for numerical stability
    cos_theta_sq = (1.0 - u[1]) / (1.0 + (a + 1.0) * ((a - 1.0) * u[1]))
    cos_theta_sq = max(0.0, min(1.0, cos_theta_sq))
    cos_theta = math.sqrt(cos_theta_sq)
    sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta_sq))
    return (sin_theta * math.cos(phi), sin_theta * math.sin(phi), cos_theta)


# --- BRDF Components ---
def v_smith_ggx_correlated(NoV, NoL, a):
    """
    Height-correlated Smith-GGX visibility function.
    Already includes the 1/(4*NoV*NoL) denominator from Cook-Torrance.
    """
    a2 = a * a
    GGXL = NoV * math.sqrt(max(0.0, (NoL - NoL * a2) * NoL + a2))
    GGXV = NoL * math.sqrt(max(0.0, (NoV - NoV * a2) * NoV + a2))
    denom = GGXV + GGXL
    if denom < 1e-7:
        return 0.0
    return 0.5 / denom


def d_charlie(NoH, a):
    """Charlie (Estevez-Kulla) NDF for cloth sheen."""
    if a < 1e-7:
        return 0.0
    inv_alpha = 1.0 / a
    cos2h = NoH * NoH
    sin2h = max(0.0, 1.0 - cos2h)
    return (2.0 + inv_alpha) * math.pow(max(sin2h, 1e-12), inv_alpha * 0.5) / (2.0 * PI)


def v_ashikhmin(NoV, NoL):
    """Neubelt-Pettineo visibility for cloth."""
    denom = 4.0 * (NoL + NoV - NoL * NoV)
    if denom < 1e-7:
        return 0.0
    return 1.0 / denom


# --- DFG Integration ---
def dfv_multiscatter(NoV, linear_roughness, num_samples):
    """
    Compute multiscatter DFG values (DFG1, DFG2) via importance-sampled
    GGX integration.

    DFG1 = Fc-weighted visibility integral
    DFG2 = total visibility integral
    """
    r_x = 0.0  # Fc-weighted
    r_y = 0.0  # total
    sin_v = math.sqrt(max(0.0, 1.0 - NoV * NoV))
    V = (sin_v, 0.0, NoV)
    inv_n = 1.0 / num_samples

    for i in range(num_samples):
        u = hammersley(i, inv_n)
        H = importance_sample_ggx(u, linear_roughness)

        # V dot H
        VdotH = V[0] * H[0] + V[1] * H[1] + V[2] * H[2]

        # Reflect V around H to get L
        L = (
            2.0 * VdotH * H[0] - V[0],
            2.0 * VdotH * H[1] - V[1],
            2.0 * VdotH * H[2] - V[2],
        )

        VoH = saturate(VdotH)
        NoL = saturate(L[2])
        NoH = saturate(H[2])

        if NoL > 0 and NoH > 0:
            v = v_smith_ggx_correlated(NoV, NoL, linear_roughness) * NoL * (VoH / NoH)
            Fc = pow5(1.0 - VoH)
            r_x += v * Fc
            r_y += v

    return (r_x * 4.0 / num_samples, r_y * 4.0 / num_samples)


def dfv_charlie(NoV, linear_roughness, num_samples):
    """
    Compute cloth sheen DFG via uniform hemisphere sampling with
    Charlie NDF and Ashikhmin visibility.
    """
    r = 0.0
    sin_v = math.sqrt(max(0.0, 1.0 - NoV * NoV))
    V = (sin_v, 0.0, NoV)
    inv_n = 1.0 / num_samples

    for i in range(num_samples):
        u = hammersley(i, inv_n)

        # Uniform hemisphere sampling
        phi = 2.0 * PI * u[0]
        cos_theta = 1.0 - u[1]
        sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
        H = (sin_theta * math.cos(phi), sin_theta * math.sin(phi), cos_theta)

        VdotH = V[0] * H[0] + V[1] * H[1] + V[2] * H[2]
        L = (
            2.0 * VdotH * H[0] - V[0],
            2.0 * VdotH * H[1] - V[1],
            2.0 * VdotH * H[2] - V[2],
        )

        VoH = saturate(VdotH)
        NoL = saturate(L[2])
        NoH = saturate(H[2])

        if NoL > 0:
            v = v_ashikhmin(NoV, NoL)
            d = d_charlie(NoH, linear_roughness)
            r += v * d * NoL * VoH  # VoH from Jacobian 1/(4*VoH)

    # Uniform PDF = 1/(2pi), factor of 4 from Jacobian
    return r * (4.0 * 2.0 * PI / num_samples)


# --- LUT Generation ---
def generate_lut(size=LUT_SIZE):
    """Generate the full DFG LUT as a flat list of float values."""
    pixels = []
    total = size * size
    for y in range(size):
        # Coordinate mapping: y=0 is top row (high roughness)
        coord = saturate((size - y + 0.5) / size)
        linear_roughness = coord * coord

        for x in range(size):
            NoV = saturate((x + 0.5) / size)

            # Multiscatter DFG
            dfg1, dfg2 = dfv_multiscatter(NoV, linear_roughness, GGX_SAMPLES)

            # Cloth sheen DFG
            charlie = dfv_charlie(NoV, linear_roughness, CHARLIE_SAMPLES)

            pixels.extend([dfg1, dfg2, charlie])

        done = (y + 1) * size
        pct = done * 100.0 / total
        if (y + 1) % 16 == 0 or y == size - 1:
            print(f"  Progress: {pct:.0f}% ({done}/{total} pixels)")

    return pixels


def write_lut(pixels, path, size=LUT_SIZE, channels=3):
    """Write the LUT to a binary file with DFGL header."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        # Header
        f.write(b"DFGL")
        f.write(struct.pack("<III", size, size, channels))
        # Pixel data
        f.write(struct.pack(f"<{len(pixels)}f", *pixels))
    print(f"Wrote {os.path.getsize(path)} bytes to {path}")


def main():
    print("Generating DFG LUT...")
    print(f"  Size: {LUT_SIZE}x{LUT_SIZE}")
    print(f"  GGX samples: {GGX_SAMPLES}")
    print(f"  Charlie samples: {CHARLIE_SAMPLES}")

    pixels = generate_lut()

    output_path = "/app/output/dfg_lut.bin"
    write_lut(pixels, output_path)
    print("Done.")


if __name__ == "__main__":
    main()
