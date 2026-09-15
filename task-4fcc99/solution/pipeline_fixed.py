#!/usr/bin/env python3
"""
Fixed version of the 2D diffusion inverse problem pipeline.

Three bugs corrected from the original pipeline.py:
1. Negative modulo in periodic boundary indices — added +grid_n before %
2. First ping-pong buffer missing requires_grad=True — added the flag
3. Loss array not zeroed between iterations — added loss.zero_()
"""

import json
import os

import numpy as np
import warp as wp

wp.init()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
with open("/app/config.json") as f:
    config = json.load(f)

N = int(config["grid_size"])
KAPPA = float(config["kappa"])
DT = float(config["dt"])
N_STEPS = int(config["n_steps"])
LR = float(config["learning_rate"])
MAX_ITER = int(config["max_iterations"])
TOL = float(config["tolerance"])

H = 1.0 / float(N)
H_INV_SQ = 1.0 / (H * H)
TOTAL_N = N * N
INV_N = 1.0 / float(TOTAL_N)


# ---------------------------------------------------------------------------
# Warp kernels
# ---------------------------------------------------------------------------
@wp.kernel
def copy_field(src: wp.array(dtype=wp.float32), dst: wp.array(dtype=wp.float32)):
    tid = wp.tid()
    dst[tid] = src[tid]


@wp.kernel
def diffusion_step(
    u_in: wp.array(dtype=wp.float32),
    u_out: wp.array(dtype=wp.float32),
    grid_n: int,
    kappa: float,
    dt: float,
    h_inv_sq: float,
):
    tid = wp.tid()
    i = tid // grid_n
    j = tid - i * grid_n

    # FIX 1: periodic neighbour indices — add grid_n before modulo
    # to ensure non-negative operands (Warp compiles to C++ where
    # negative % gives negative results unlike Python)
    ip = ((i + 1) % grid_n) * grid_n + j
    im = ((i - 1 + grid_n) % grid_n) * grid_n + j
    jp = i * grid_n + ((j + 1) % grid_n)
    jm = i * grid_n + ((j - 1 + grid_n) % grid_n)

    # 5-point Laplacian stencil
    lap = (u_in[ip] + u_in[im] + u_in[jp] + u_in[jm] - 4.0 * u_in[tid]) * h_inv_sq
    u_out[tid] = u_in[tid] + kappa * dt * lap


@wp.kernel
def mse_loss_kernel(
    pred: wp.array(dtype=wp.float32),
    tgt: wp.array(dtype=wp.float32),
    loss: wp.array(dtype=wp.float32),
    inv_n: float,
):
    tid = wp.tid()
    diff = pred[tid] - tgt[tid]
    wp.atomic_add(loss, 0, diff * diff * inv_n)


@wp.kernel
def gradient_step(
    param: wp.array(dtype=wp.float32),
    grad: wp.array(dtype=wp.float32),
    lr: float,
):
    tid = wp.tid()
    param[tid] = param[tid] - lr * grad[tid]


# ---------------------------------------------------------------------------
# Main optimisation loop
# ---------------------------------------------------------------------------
def main():
    target_np = np.load("/app/target_field.npy").astype(np.float32).flatten()
    target = wp.array(target_np, dtype=wp.float32)

    ic = wp.array(
        np.zeros(TOTAL_N, dtype=np.float32), dtype=wp.float32, requires_grad=True
    )

    # FIX 2: ALL buffers need requires_grad=True for gradient flow
    # (original code omitted it on buffers[0], breaking adjoint propagation
    #  from the forward chain back to the initial condition)
    buffers = [
        wp.zeros(TOTAL_N, dtype=wp.float32, requires_grad=True)
        for _ in range(N_STEPS + 1)
    ]

    loss = wp.zeros(1, dtype=wp.float32, requires_grad=True)
    final_mse = float("inf")

    for it in range(MAX_ITER):
        # FIX 3: zero the loss accumulator before each forward pass
        # (original code never zeroed it, so MSE accumulated across iterations)
        loss.zero_()

        tape = wp.Tape()
        with tape:
            wp.launch(copy_field, dim=TOTAL_N, inputs=[ic, buffers[0]])

            for s in range(N_STEPS):
                wp.launch(
                    diffusion_step,
                    dim=TOTAL_N,
                    inputs=[buffers[s], buffers[s + 1], N, KAPPA, DT, H_INV_SQ],
                )

            wp.launch(
                mse_loss_kernel,
                dim=TOTAL_N,
                inputs=[buffers[N_STEPS], target, loss, INV_N],
            )

        tape.backward(loss)

        final_mse = float(loss.numpy()[0])

        if it % 100 == 0:
            print(f"[iter {it:>5d}] MSE = {final_mse:.6e}")

        if final_mse < TOL:
            print(f"Converged at iteration {it}, MSE = {final_mse:.6e}")
            break

        ic_grad = tape.gradients[ic]
        wp.launch(gradient_step, dim=TOTAL_N, inputs=[ic, ic_grad, LR])

        tape.zero()

    # ------------------------------------------------------------------
    # Save results
    # ------------------------------------------------------------------
    os.makedirs("/app/results", exist_ok=True)
    ic_result = ic.numpy().reshape(N, N)
    np.save("/app/results/optimized_ic.npy", ic_result)

    with open("/app/results/final_mse.txt", "w") as f:
        f.write(f"{final_mse:.10e}")

    print(f"\nDone. Final MSE: {final_mse:.6e}")
    print("Results saved to /app/results/")


if __name__ == "__main__":
    main()
