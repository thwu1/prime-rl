#!/usr/bin/env python3
"""Fix all bugs in the SGWT pipeline: Makefile, C code, ctypes wrapper, Python modules."""


def fix_makefile():
    """Fix TARGET name (libsgwt.so -> libsgwt_native.so) and add -lm linker flag."""
    makefile = (
        "CC = gcc\n"
        "CFLAGS = -Wall -O2 -fPIC\n"
        "\n"
        "TARGET = libsgwt_native.so\n"
        "\n"
        "all: $(TARGET)\n"
        "\n"
        "$(TARGET): sgwt_native/cheby.c\n"
        "\t$(CC) $(CFLAGS) -shared -o $@ $< -lm\n"
        "\n"
        "clean:\n"
        "\trm -f $(TARGET)\n"
    )
    with open("/app/Makefile", "w") as f:
        f.write(makefile)


def fix_c_code():
    """Fix three-term recurrence sign: + twf_old -> - twf_old."""
    with open("/app/sgwt_native/cheby.c", "r") as f:
        code = f.read()
    code = code.replace("+ twf_old[n];", "- twf_old[n];")
    with open("/app/sgwt_native/cheby.c", "w") as f:
        f.write(code)


def fix_filtering():
    """Fix ctypes result buffer reshape: (Nscales, N).T -> (N, Nscales)."""
    with open("/app/sgwt_lib/filtering.py", "r") as f:
        code = f.read()
    code = code.replace(
        "result_buf.reshape(Nscales, N).T",
        "result_buf.reshape(N, Nscales)"
    )
    with open("/app/sgwt_lib/filtering.py", "w") as f:
        f.write(code)


def fix_graph():
    """Fix degree matrix (edge count -> weight sum) and remove eigenvalue clipping."""
    code = '''"""Graph construction and Laplacian computation for SGWT."""
import numpy as np


def build_laplacian(n_nodes, edges):
    W = np.zeros((n_nodes, n_nodes))
    for edge in edges:
        i, j, w = int(edge[0]), int(edge[1]), float(edge[2])
        W[i, j] = w
        W[j, i] = w
    D = np.diag(W.sum(axis=1))
    L = D - W
    return L


def compute_fourier_basis(L):
    eigenvalues, eigenvectors = np.linalg.eigh(L)
    idx = np.argsort(eigenvalues)
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]
    eigenvalues = np.maximum(eigenvalues, 0.0)
    return eigenvalues, eigenvectors
'''
    with open("/app/sgwt_lib/graph.py", "w") as f:
        f.write(code)


def fix_kernels():
    """Fix Meyer v(x) coefficient (21 -> 20) and MexicanHat exponent (2 -> 4)."""
    with open("/app/sgwt_lib/kernels.py", "r") as f:
        code = f.read()
    code = code.replace("21.0 * x ** 3", "20.0 * x ** 3")
    code = code.replace("(0.4 * lmin)) ** 2)", "(0.4 * lmin)) ** 4)")
    with open("/app/sgwt_lib/kernels.py", "w") as f:
        f.write(code)


def fix_scales():
    """Fix log scale ordering: ascending -> descending."""
    with open("/app/sgwt_lib/scales.py", "r") as f:
        code = f.read()
    code = code.replace(
        "np.linspace(np.log(scale_min), np.log(scale_max), Nscales)",
        "np.linspace(np.log(scale_max), np.log(scale_min), Nscales)"
    )
    with open("/app/sgwt_lib/scales.py", "w") as f:
        f.write(code)


def fix_frames():
    """Fix frame bounds: sum of abs -> sum of squares."""
    code = '''"""Frame bounds estimation for wavelet filterbanks."""
import numpy as np


def compute_frame_bounds(kernel_responses):
    sum_sq = np.sum(kernel_responses ** 2, axis=0)
    return float(np.min(sum_sq)), float(np.max(sum_sq))
'''
    with open("/app/sgwt_lib/frames.py", "w") as f:
        f.write(code)


def implement_jackson():
    """Implement Jackson-Chebyshev coefficient computation from spec."""
    code = '''"""Jackson-Chebyshev coefficients for ideal band-pass approximation."""
import numpy as np


def compute_jackson_cheby_coeff(filter_bounds, delta_lambda, m):
    a1 = (delta_lambda[1] - delta_lambda[0]) / 2.0
    a2 = (delta_lambda[1] + delta_lambda[0]) / 2.0
    fb0 = (filter_bounds[0] - a2) / a1
    fb1 = (filter_bounds[1] - a2) / a1

    ch = np.zeros(m + 1)
    ch[0] = (2.0 / np.pi) * (np.arccos(fb0) - np.arccos(fb1))
    for i in range(1, m + 1):
        ch[i] = (2.0 / (np.pi * i)) * (
            np.sin(i * np.arccos(fb0)) - np.sin(i * np.arccos(fb1))
        )

    jch = np.zeros(m + 1)
    alpha = np.pi / (m + 2)
    for i in range(m + 1):
        jch[i] = (1.0 / np.sin(alpha)) * (
            (1.0 - i / (m + 2)) * np.sin(alpha) * np.cos(i * alpha)
            + (1.0 / (m + 2)) * np.cos(alpha) * np.sin(i * alpha)
        )

    return ch * jch
'''
    with open("/app/sgwt_lib/jackson.py", "w") as f:
        f.write(code)


if __name__ == "__main__":
    fix_makefile()
    fix_c_code()
    fix_filtering()
    fix_graph()
    fix_kernels()
    fix_scales()
    fix_frames()
    implement_jackson()
    print("All fixes applied.")
