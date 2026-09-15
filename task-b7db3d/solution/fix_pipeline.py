#!/usr/bin/env python3
"""Fix all issues in the PBR multi-backend BRDF pipeline."""

import os

APP = '/app'


def write_file(name, content):
    path = os.path.join(APP, name)
    with open(path, 'w') as f:
        f.write(content)


# ================================================================
# 1. Fix the Makefile (3 bugs)
# ================================================================
write_file('Makefile', """CC = gcc
CFLAGS = -O2 -Wall -fPIC
LDFLAGS = -shared -lm
TARGET = libbrdf.so

all: $(TARGET)

$(TARGET): brdf_kernel.o
\t$(CC) $(LDFLAGS) $< -o $@

brdf_kernel.o: brdf_kernel.c brdf_kernel.h
\t$(CC) $(CFLAGS) -c $< -o $@

clean:
\trm -f *.o $(TARGET)
""")


# ================================================================
# 2. Fix brdf_kernel.c (5 bugs)
# ================================================================
write_file('brdf_kernel.c', r"""#include "brdf_kernel.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

double brdf_D_GGX(double NoH, double alpha) {
    double a2 = alpha * alpha;
    double f = NoH * NoH * (a2 - 1.0) + 1.0;
    return a2 / (M_PI * f * f);
}

double brdf_D_Charlie(double NoH, double roughness) {
    double sin2h = fmax(1.0 - NoH * NoH, 0.0);
    if (sin2h < 1e-15) return 0.0;
    double inv_r = 1.0 / roughness;
    return (2.0 + inv_r) * pow(sin2h, inv_r * 0.5) / (2.0 * M_PI);
}

double brdf_V_SmithGGX(double NoV, double NoL, double alpha) {
    double a2 = alpha * alpha;
    double GGXV = NoL * sqrt(NoV * NoV * (1.0 - a2) + a2);
    double GGXL = NoV * sqrt(NoL * NoL * (1.0 - a2) + a2);
    return 0.5 / (GGXV + GGXL + 1e-7);
}

double brdf_V_Neubelt(double NoV, double NoL) {
    return 1.0 / (4.0 * (NoL + NoV - NoL * NoV) + 1e-7);
}

double brdf_F_Schlick_scalar(double VoH, double f0) {
    return f0 + (1.0 - f0) * pow(1.0 - VoH, 5.0);
}

double hammersley_radical_inverse(unsigned int bits) {
    bits = (bits << 16u) | (bits >> 16u);
    bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
    bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
    bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
    bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
    return (double)bits * 2.3283064365386963e-10;
}

Vec3 sample_GGX(double xi_x, double xi_y, double alpha) {
    double a2 = alpha * alpha;
    double cosTheta2 = (1.0 - xi_y) / (1.0 + (a2 - 1.0) * xi_y);
    double cosTheta = sqrt(fmax(cosTheta2, 0.0));
    double sinTheta = sqrt(fmax(1.0 - cosTheta2, 0.0));
    double phi = 2.0 * M_PI * xi_x;
    Vec3 H;
    H.x = sinTheta * cos(phi);
    H.y = sinTheta * sin(phi);
    H.z = cosTheta;
    return H;
}

Vec3 sample_hemisphere_cosine(double xi_x, double xi_y) {
    double sinTheta = sqrt(xi_y);
    double cosTheta = sqrt(fmax(1.0 - xi_y, 0.0));
    double phi = 2.0 * M_PI * xi_x;
    Vec3 H;
    H.x = sinTheta * cos(phi);
    H.y = sinTheta * sin(phi);
    H.z = cosTheta;
    return H;
}

Vec3 sample_hemisphere_uniform(double xi_x, double xi_y) {
    double cosTheta = xi_y;
    double sinTheta = sqrt(fmax(1.0 - cosTheta * cosTheta, 0.0));
    double phi = 2.0 * M_PI * xi_x;
    Vec3 H;
    H.x = sinTheta * cos(phi);
    H.y = sinTheta * sin(phi);
    H.z = cosTheta;
    return H;
}

Vec3 sample_Charlie(double xi_x, double xi_y, double roughness) {
    double sinTheta = pow(fmax(xi_y, 1e-10), roughness / (2.0 * roughness + 1.0));
    double cosTheta = sqrt(fmax(1.0 - sinTheta * sinTheta, 0.0));
    double phi = 2.0 * M_PI * xi_x;
    Vec3 H;
    H.x = sinTheta * cos(phi);
    H.y = sinTheta * sin(phi);
    H.z = cosTheta;
    return H;
}
""")


# ================================================================
# 3. Complete ffi_bridge.py
# ================================================================
write_file('ffi_bridge.py', """import ctypes
import os

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libbrdf.so')
_lib = ctypes.CDLL(_LIB_PATH)

class Vec3(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("z", ctypes.c_double)]

_lib.brdf_D_GGX.argtypes = [ctypes.c_double, ctypes.c_double]
_lib.brdf_D_GGX.restype = ctypes.c_double

_lib.brdf_V_SmithGGX.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
_lib.brdf_V_SmithGGX.restype = ctypes.c_double

_lib.brdf_F_Schlick_scalar.argtypes = [ctypes.c_double, ctypes.c_double]
_lib.brdf_F_Schlick_scalar.restype = ctypes.c_double

_lib.brdf_D_Charlie.argtypes = [ctypes.c_double, ctypes.c_double]
_lib.brdf_D_Charlie.restype = ctypes.c_double

_lib.brdf_V_Neubelt.argtypes = [ctypes.c_double, ctypes.c_double]
_lib.brdf_V_Neubelt.restype = ctypes.c_double

_lib.sample_GGX.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
_lib.sample_GGX.restype = Vec3

_lib.sample_hemisphere_cosine.argtypes = [ctypes.c_double, ctypes.c_double]
_lib.sample_hemisphere_cosine.restype = Vec3

_lib.sample_hemisphere_uniform.argtypes = [ctypes.c_double, ctypes.c_double]
_lib.sample_hemisphere_uniform.restype = Vec3

_lib.sample_Charlie.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
_lib.sample_Charlie.restype = Vec3

_lib.hammersley_radical_inverse.argtypes = [ctypes.c_uint]
_lib.hammersley_radical_inverse.restype = ctypes.c_double


def D_GGX(NoH, alpha):
    return _lib.brdf_D_GGX(NoH, alpha)

def V_SmithGGX(NoV, NoL, alpha):
    return _lib.brdf_V_SmithGGX(NoV, NoL, alpha)

def F_Schlick(VoH, f0):
    return _lib.brdf_F_Schlick_scalar(VoH, f0)

def D_Charlie(NoH, roughness):
    return _lib.brdf_D_Charlie(NoH, roughness)

def V_Neubelt(NoV, NoL):
    return _lib.brdf_V_Neubelt(NoV, NoL)

def sample_GGX(xi_x, xi_y, alpha):
    v = _lib.sample_GGX(xi_x, xi_y, alpha)
    return (v.x, v.y, v.z)

def sample_cosine(xi_x, xi_y):
    v = _lib.sample_hemisphere_cosine(xi_x, xi_y)
    return (v.x, v.y, v.z)

def sample_uniform(xi_x, xi_y):
    v = _lib.sample_hemisphere_uniform(xi_x, xi_y)
    return (v.x, v.y, v.z)

def sample_charlie(xi_x, xi_y, roughness):
    v = _lib.sample_Charlie(xi_x, xi_y, roughness)
    return (v.x, v.y, v.z)

def hammersley_ri(i):
    return _lib.hammersley_radical_inverse(ctypes.c_uint(i))
""")


# ================================================================
# 4. Complete integrators.py
# ================================================================
write_file('integrators.py', """import math
from ffi_bridge import (D_GGX, V_SmithGGX,
                         sample_GGX as _sample_ggx,
                         sample_cosine as _sample_cosine,
                         sample_uniform as _sample_uniform,
                         sample_charlie as _sample_charlie,
                         V_Neubelt, hammersley_ri)


def integrate_dfg_ggx_is(NoV, roughness, num_samples=1024):
    alpha = roughness * roughness
    V_x = math.sqrt(max(1.0 - NoV * NoV, 0.0))
    V_z = NoV
    dfg_x = 0.0
    dfg_y = 0.0
    for i in range(num_samples):
        xi_x = i / num_samples
        xi_y = hammersley_ri(i)
        Hx, Hy, Hz = _sample_ggx(xi_x, xi_y, alpha)
        VoH = max(V_x * Hx + V_z * Hz, 0.0)
        Lz = max(2.0 * VoH * Hz - V_z, 0.0)
        NoH = max(Hz, 0.0)
        if Lz > 0 and NoH > 0:
            v = V_SmithGGX(NoV, Lz, alpha)
            w = v * 4.0 * VoH * Lz / (NoH + 1e-10)
            Fc = (1.0 - VoH) ** 5
            dfg_x += w * (1.0 - Fc)
            dfg_y += w * Fc
    return (dfg_x / num_samples, dfg_y / num_samples)


def integrate_dfg_cosine(NoV, roughness, num_samples=1024):
    alpha = roughness * roughness
    V_x = math.sqrt(max(1.0 - NoV * NoV, 0.0))
    V_z = NoV
    dfg_x = 0.0
    dfg_y = 0.0
    for i in range(num_samples):
        xi_x = i / num_samples
        xi_y = hammersley_ri(i)
        Hx, Hy, Hz = _sample_cosine(xi_x, xi_y)
        VoH = max(V_x * Hx + V_z * Hz, 0.0)
        Lz = max(2.0 * VoH * Hz - V_z, 0.0)
        NoH = max(Hz, 0.0)
        if Lz > 0 and NoH > 0:
            d = D_GGX(NoH, alpha)
            v = V_SmithGGX(NoV, Lz, alpha)
            w = d * v * 4.0 * VoH * Lz * math.pi / (NoH + 1e-10)
            Fc = (1.0 - VoH) ** 5
            dfg_x += w * (1.0 - Fc)
            dfg_y += w * Fc
    return (dfg_x / num_samples, dfg_y / num_samples)


def integrate_dfg_uniform(NoV, roughness, num_samples=1024):
    alpha = roughness * roughness
    V_x = math.sqrt(max(1.0 - NoV * NoV, 0.0))
    V_z = NoV
    dfg_x = 0.0
    dfg_y = 0.0
    for i in range(num_samples):
        xi_x = i / num_samples
        xi_y = hammersley_ri(i)
        Hx, Hy, Hz = _sample_uniform(xi_x, xi_y)
        VoH = max(V_x * Hx + V_z * Hz, 0.0)
        Lz = max(2.0 * VoH * Hz - V_z, 0.0)
        NoH = max(Hz, 0.0)
        if Lz > 0 and NoH > 0:
            d = D_GGX(NoH, alpha)
            v = V_SmithGGX(NoV, Lz, alpha)
            w = d * v * 4.0 * VoH * Lz * 2.0 * math.pi
            Fc = (1.0 - VoH) ** 5
            dfg_x += w * (1.0 - Fc)
            dfg_y += w * Fc
    return (dfg_x / num_samples, dfg_y / num_samples)


def integrate_dfg_cloth(NoV, roughness, num_samples=1024):
    V_x = math.sqrt(max(1.0 - NoV * NoV, 0.0))
    V_z = NoV
    result = 0.0
    for i in range(num_samples):
        xi_x = i / num_samples
        xi_y = hammersley_ri(i)
        Hx, Hy, Hz = _sample_charlie(xi_x, xi_y, roughness)
        VoH = max(V_x * Hx + V_z * Hz, 0.0)
        Lz = max(2.0 * VoH * Hz - V_z, 0.0)
        NoH = max(Hz, 0.0)
        if Lz > 0 and NoH > 0:
            v = V_Neubelt(NoV, Lz)
            w = v * 4.0 * VoH * Lz / (NoH + 1e-10)
            result += w
    return result / num_samples
""")


# ================================================================
# 5. Complete convergence.py
# ================================================================
write_file('convergence.py', """import json
import math
from integrators import integrate_dfg_ggx_is, integrate_dfg_cosine, integrate_dfg_uniform

ROUGHNESS_BANDS = [0.1, 0.3, 0.5, 0.7, 0.9]
REFERENCE_SAMPLES = 8192
EVAL_SAMPLES = 1024
TEST_NOV = 0.5


def compute_rmse(x, y, ref_x, ref_y):
    dx = x - ref_x
    dy = y - ref_y
    return math.sqrt((dx * dx + dy * dy) / 2.0)


def rank_strategies_for_roughness(roughness):
    ref_x, ref_y = integrate_dfg_ggx_is(TEST_NOV, roughness,
                                          num_samples=REFERENCE_SAMPLES)
    strategies = {
        'ggx_is': integrate_dfg_ggx_is,
        'cosine': integrate_dfg_cosine,
        'uniform': integrate_dfg_uniform,
    }
    rmse = {}
    for name, fn in strategies.items():
        x, y = fn(TEST_NOV, roughness, num_samples=EVAL_SAMPLES)
        rmse[name] = compute_rmse(x, y, ref_x, ref_y)
    ranking = sorted(rmse.keys(), key=lambda k: rmse[k])
    return {'ranking': ranking, 'rmse': {k: round(v, 8) for k, v in rmse.items()}}


def generate_report():
    report = {'roughness_bands': {}}
    for rough in ROUGHNESS_BANDS:
        result = rank_strategies_for_roughness(rough)
        report['roughness_bands'][str(rough)] = result
    return report
""")


# ================================================================
# 6. Complete pipeline.py
# ================================================================
write_file('pipeline.py', """import subprocess
import json
import os
import sys

LUT_SIZE = 16


def build_library():
    subprocess.run(['make', '-C', '/app', 'clean'], capture_output=True)
    result = subprocess.run(['make', '-C', '/app'], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Build failed:\\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile('/app/libbrdf.so'):
        print("ERROR: libbrdf.so not produced", file=sys.stderr)
        sys.exit(1)
    print("Library built successfully.")


def generate_lut():
    from integrators import integrate_dfg_ggx_is, integrate_dfg_cloth
    lut = {'size': LUT_SIZE, 'standard': [], 'cloth': []}
    for i_nov in range(LUT_SIZE):
        nov = max((i_nov + 0.5) / LUT_SIZE, 0.01)
        std_row = []
        cloth_row = []
        for i_rough in range(LUT_SIZE):
            rough = max((i_rough + 0.5) / LUT_SIZE, 0.01)
            x, y = integrate_dfg_ggx_is(nov, rough, num_samples=4096)
            std_row.append([round(x, 6), round(y, 6)])
            c = integrate_dfg_cloth(nov, rough, num_samples=4096)
            cloth_row.append(round(c, 6))
        lut['standard'].append(std_row)
        lut['cloth'].append(cloth_row)
    with open('/app/dfg_lut.json', 'w') as f:
        json.dump(lut, f, indent=2)


if __name__ == '__main__':
    build_library()
    sys.path.insert(0, '/app')
    from convergence import generate_report
    report = generate_report()
    with open('/app/convergence_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("Convergence report written.")
    generate_lut()
    print("DFG LUT written.")
    print("Pipeline complete.")
""")


print("All pipeline files fixed and completed.")
