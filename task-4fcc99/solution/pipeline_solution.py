#!/usr/bin/env python3
"""
Two-phase diffusion inverse problem solver using NVIDIA Warp.

Strategy:
  1. Estimate kappa_2 from calibration data (known_ic_b, target_b):
     - Run phase 1 once (fixed kappa_1, known IC) to get deterministic intermediate
     - Optimize log(kappa_2) via gradient descent through phase 2 only
     - Use exp transform to keep kappa_2 positive

  2. Recover IC_A using estimated kappa_2:
     - Optimize IC through the full two-phase simulation
     - Both kappas are now fixed; only the IC is differentiable
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
KAPPA_1 = float(config["kappa_1"])
N_STEPS_1 = int(config["n_steps_phase1"])
N_STEPS_2 = int(config["n_steps_phase2"])
DT = float(config["dt"])
MAX_ITER = int(config["max_iterations"])
TOL = float(config["tolerance"])

H = 1.0 / float(N)
H_INV_SQ = 1.0 / (H * H)
TOTAL_N = N * N
INV_N = 1.0 / float(TOTAL_N)
TOTAL_STEPS = N_STEPS_1 + N_STEPS_2


# ---------------------------------------------------------------------------
# Warp kernels
# ---------------------------------------------------------------------------
@wp.kernel
def copy_field(src: wp.array(dtype=wp.float32), dst: wp.array(dtype=wp.float32)):
    """Copy src into dst (recorded on tape for gradient flow)."""
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
    """One explicit-Euler step of the 2D heat equation with periodic BC.
    kappa is a fixed float (not differentiable)."""
    tid = wp.tid()
    i = tid // grid_n
    j = tid - i * grid_n

    # Periodic neighbour indices — add grid_n before modulo to avoid
    # negative results in Warp's compiled C++ (unlike Python, C++ % can
    # return negative values for negative operands).
    ip = ((i + 1) % grid_n) * grid_n + j
    im = ((i - 1 + grid_n) % grid_n) * grid_n + j
    jp = i * grid_n + ((j + 1) % grid_n)
    jm = i * grid_n + ((j - 1 + grid_n) % grid_n)

    lap = (u_in[ip] + u_in[im] + u_in[jp] + u_in[jm] - 4.0 * u_in[tid]) * h_inv_sq
    u_out[tid] = u_in[tid] + kappa * dt * lap


@wp.kernel
def diffusion_step_diff_kappa(
    u_in: wp.array(dtype=wp.float32),
    u_out: wp.array(dtype=wp.float32),
    grid_n: int,
    kappa_arr: wp.array(dtype=wp.float32),
    dt: float,
    h_inv_sq: float,
):
    """Diffusion step where kappa is read from a 1-element array so that
    gradients can flow through it via wp.Tape."""
    tid = wp.tid()
    i = tid // grid_n
    j = tid - i * grid_n

    ip = ((i + 1) % grid_n) * grid_n + j
    im = ((i - 1 + grid_n) % grid_n) * grid_n + j
    jp = i * grid_n + ((j + 1) % grid_n)
    jm = i * grid_n + ((j - 1 + grid_n) % grid_n)

    kappa = kappa_arr[0]
    lap = (u_in[ip] + u_in[im] + u_in[jp] + u_in[jm] - 4.0 * u_in[tid]) * h_inv_sq
    u_out[tid] = u_in[tid] + kappa * dt * lap


@wp.kernel
def exp_transform(
    log_val: wp.array(dtype=wp.float32),
    out_val: wp.array(dtype=wp.float32),
):
    """Compute out = exp(log_val) element-wise (differentiable)."""
    tid = wp.tid()
    out_val[tid] = wp.exp(log_val[tid])


@wp.kernel
def mse_loss_kernel(
    pred: wp.array(dtype=wp.float32),
    tgt: wp.array(dtype=wp.float32),
    loss: wp.array(dtype=wp.float32),
    inv_n: float,
):
    """MSE loss via atomic reduction (differentiable through wp.Tape)."""
    tid = wp.tid()
    diff = pred[tid] - tgt[tid]
    wp.atomic_add(loss, 0, diff * diff * inv_n)


@wp.kernel
def gradient_step(
    param: wp.array(dtype=wp.float32),
    grad: wp.array(dtype=wp.float32),
    lr: float,
):
    """In-place gradient-descent update."""
    tid = wp.tid()
    param[tid] = param[tid] - lr * grad[tid]


# ---------------------------------------------------------------------------
# Stage 1: Estimate kappa_2 from calibration data
# ---------------------------------------------------------------------------
def estimate_kappa2():
    print("=== Stage 1: Estimating kappa_2 from calibration data ===")

    known_ic_np = np.load("/app/known_ic_b.npy").astype(np.float32).flatten()
    target_b_np = np.load("/app/target_b.npy").astype(np.float32).flatten()

    known_ic = wp.array(known_ic_np, dtype=wp.float32)
    target_b = wp.array(target_b_np, dtype=wp.float32)

    # ---- Run phase 1 once (deterministic, no gradient needed) ----
    p1_bufs = [wp.zeros(TOTAL_N, dtype=wp.float32) for _ in range(N_STEPS_1 + 1)]
    wp.launch(copy_field, dim=TOTAL_N, inputs=[known_ic, p1_bufs[0]])
    for s in range(N_STEPS_1):
        wp.launch(
            diffusion_step,
            dim=TOTAL_N,
            inputs=[p1_bufs[s], p1_bufs[s + 1], N, KAPPA_1, DT, H_INV_SQ],
        )
    intermediate = p1_bufs[N_STEPS_1]

    # ---- Optimize log(kappa_2) through phase 2 ----
    # Start with initial guess kappa_2 = 0.01 (i.e. log(0.01))
    log_k2 = wp.array(
        [np.float32(np.log(0.01))], dtype=wp.float32, requires_grad=True
    )
    k2_arr = wp.zeros(1, dtype=wp.float32, requires_grad=True)

    p2_bufs = [
        wp.zeros(TOTAL_N, dtype=wp.float32, requires_grad=True)
        for _ in range(N_STEPS_2 + 1)
    ]
    loss = wp.zeros(1, dtype=wp.float32, requires_grad=True)

    lr = 50.0

    for it in range(500):
        loss.zero_()

        # Re-initialise phase 2 input from intermediate (outside tape)
        wp.launch(copy_field, dim=TOTAL_N, inputs=[intermediate, p2_bufs[0]])

        tape = wp.Tape()
        with tape:
            # exp transform: kappa_2 = exp(log_kappa_2)
            wp.launch(exp_transform, dim=1, inputs=[log_k2, k2_arr])

            # Phase 2 forward with differentiable kappa
            for s in range(N_STEPS_2):
                wp.launch(
                    diffusion_step_diff_kappa,
                    dim=TOTAL_N,
                    inputs=[p2_bufs[s], p2_bufs[s + 1], N, k2_arr, DT, H_INV_SQ],
                )

            # Loss
            wp.launch(
                mse_loss_kernel,
                dim=TOTAL_N,
                inputs=[p2_bufs[N_STEPS_2], target_b, loss, INV_N],
            )

        tape.backward(loss)

        mse_val = float(loss.numpy()[0])
        k2_val = float(k2_arr.numpy()[0])

        if it % 50 == 0:
            print(f"  [iter {it:>4d}] MSE={mse_val:.6e}  kappa2={k2_val:.6f}")

        if mse_val < 1e-10:
            print(f"  Converged at iter {it}")
            break

        grad = tape.gradients[log_k2]
        wp.launch(gradient_step, dim=1, inputs=[log_k2, grad, lr])
        tape.zero()

    estimated = float(k2_arr.numpy()[0])
    print(f"  Estimated kappa_2 = {estimated:.6f}\n")
    return estimated


# ---------------------------------------------------------------------------
# Stage 2: Recover IC_A using estimated kappa_2
# ---------------------------------------------------------------------------
def recover_ic_a(est_k2):
    print(f"=== Stage 2: Recovering IC_A (kappa_2={est_k2:.6f}) ===")

    target_a_np = np.load("/app/target_a.npy").astype(np.float32).flatten()
    target_a = wp.array(target_a_np, dtype=wp.float32)

    ic = wp.array(
        np.zeros(TOTAL_N, dtype=np.float32), dtype=wp.float32, requires_grad=True
    )

    # Buffer chain for full two-phase simulation
    bufs = [
        wp.zeros(TOTAL_N, dtype=wp.float32, requires_grad=True)
        for _ in range(TOTAL_STEPS + 1)
    ]
    loss = wp.zeros(1, dtype=wp.float32, requires_grad=True)

    lr = 200.0
    final_mse = float("inf")

    for it in range(MAX_ITER):
        loss.zero_()

        tape = wp.Tape()
        with tape:
            # Copy IC into first buffer
            wp.launch(copy_field, dim=TOTAL_N, inputs=[ic, bufs[0]])

            # Phase 1: fixed kappa_1
            for s in range(N_STEPS_1):
                wp.launch(
                    diffusion_step,
                    dim=TOTAL_N,
                    inputs=[bufs[s], bufs[s + 1], N, KAPPA_1, DT, H_INV_SQ],
                )

            # Phase 2: fixed estimated kappa_2
            for s in range(N_STEPS_2):
                idx = N_STEPS_1 + s
                wp.launch(
                    diffusion_step,
                    dim=TOTAL_N,
                    inputs=[bufs[idx], bufs[idx + 1], N, est_k2, DT, H_INV_SQ],
                )

            # Loss
            wp.launch(
                mse_loss_kernel,
                dim=TOTAL_N,
                inputs=[bufs[TOTAL_STEPS], target_a, loss, INV_N],
            )

        tape.backward(loss)
        final_mse = float(loss.numpy()[0])

        if it % 200 == 0:
            print(f"  [iter {it:>5d}] MSE={final_mse:.6e}")

        if final_mse < TOL:
            print(f"  Converged at iter {it}, MSE={final_mse:.6e}")
            break

        ic_grad = tape.gradients[ic]
        wp.launch(gradient_step, dim=TOTAL_N, inputs=[ic, ic_grad, lr])
        tape.zero()

    return ic, final_mse


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    est_k2 = estimate_kappa2()
    ic, final_mse = recover_ic_a(est_k2)

    os.makedirs("/app/results", exist_ok=True)

    ic_np = ic.numpy().reshape(N, N)
    np.save("/app/results/optimized_ic_a.npy", ic_np)

    with open("/app/results/estimated_kappa2.txt", "w") as f:
        f.write(f"{est_k2:.10e}")

    with open("/app/results/final_mse.txt", "w") as f:
        f.write(f"{final_mse:.10e}")

    print(f"\nDone. kappa_2={est_k2:.6f}, final MSE={final_mse:.6e}")
    print("Results saved to /app/results/")


if __name__ == "__main__":
    main()
