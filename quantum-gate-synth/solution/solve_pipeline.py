"""
Quantum circuit synthesis via variational optimization with analytical gradients.

Uses an alternating-layer ansatz on 3 qubits with linear connectivity:
  [SQ_layer] -> [XXPlusYY(0,1)] -> [XXPlusYY(1,2)] -> ... -> [SQ_layer_final]

where SQ_layer applies RZ(c)·SX·RZ(b)·SX·RZ(a) on each qubit (universal SU(2)).

The adjoint method computes exact gradients in O(K + P) matrix operations
(K = factors, P = parameters), enabling fast L-BFGS-B convergence with
hundreds of random restarts.

"""
import json
import os
import sys
import time

import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, "/app")
from target_unitary import get_target_unitary

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DIM = 8
I2 = np.eye(2, dtype=np.complex128)
I8 = np.eye(DIM, dtype=np.complex128)

SX_MAT = 0.5 * np.array(
    [[1 + 1j, 1 - 1j], [1 - 1j, 1 + 1j]], dtype=np.complex128
)

N_LAYERS = 10
N_QUBITS = 3
SQ_PER_QUBIT = 3          # a, b, c
SQ_TOTAL = SQ_PER_QUBIT * N_QUBITS   # 9
LAYER_PARAMS = SQ_TOTAL + 4           # 13
TOTAL_PARAMS = N_LAYERS * LAYER_PARAMS + SQ_TOTAL  # 139

# ---------------------------------------------------------------------------
# Gate matrices and derivatives
# ---------------------------------------------------------------------------

def rz(theta):
    h = theta / 2.0
    return np.array(
        [[np.exp(-1j * h), 0], [0, np.exp(1j * h)]], dtype=np.complex128
    )

def drz(theta):
    h = theta / 2.0
    return np.array(
        [[-0.5j * np.exp(-1j * h), 0], [0, 0.5j * np.exp(1j * h)]],
        dtype=np.complex128,
    )

def xxp(theta, beta):
    c, s = np.cos(theta / 2.0), np.sin(theta / 2.0)
    eb = np.exp(1j * beta)
    return np.array(
        [[1, 0, 0, 0],
         [0, c, 1j * s * eb, 0],
         [0, 1j * s / eb, c, 0],
         [0, 0, 0, 1]],
        dtype=np.complex128,
    )

def dxxp_dt(theta, beta):
    c, s = np.cos(theta / 2.0), np.sin(theta / 2.0)
    eb = np.exp(1j * beta)
    return np.array(
        [[0, 0, 0, 0],
         [0, -s / 2, 1j * c / 2 * eb, 0],
         [0, 1j * c / 2 / eb, -s / 2, 0],
         [0, 0, 0, 0]],
        dtype=np.complex128,
    )

def dxxp_db(theta, beta):
    s = np.sin(theta / 2.0)
    eb = np.exp(1j * beta)
    return np.array(
        [[0, 0, 0, 0],
         [0, 0, -s * eb, 0],
         [0, s / eb, 0, 0],
         [0, 0, 0, 0]],
        dtype=np.complex128,
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def kron3(a, b, c):
    return np.kron(np.kron(a, b), c)


def _build_sq(p9):
    """Build the 8x8 SQ-layer matrix and its 9 parameter derivatives.

    p9 = [a0, a1, a2, b0, b1, b2, c0, c1, c2]
    u_q = RZ(c_q) @ SX @ RZ(b_q) @ SX @ RZ(a_q)
    """
    a, b, c = p9[0:3], p9[3:6], p9[6:9]
    u = [rz(c[q]) @ SX_MAT @ rz(b[q]) @ SX_MAT @ rz(a[q]) for q in range(3)]
    mat = kron3(u[0], u[1], u[2])

    derivs = []
    for q in range(3):
        # d/d(a_q)
        du = rz(c[q]) @ SX_MAT @ rz(b[q]) @ SX_MAT @ drz(a[q])
        uc = list(u); uc[q] = du
        derivs.append((q, kron3(*uc)))
        # d/d(b_q)
        du = rz(c[q]) @ SX_MAT @ drz(b[q]) @ SX_MAT @ rz(a[q])
        uc = list(u); uc[q] = du
        derivs.append((3 + q, kron3(*uc)))
        # d/d(c_q)
        du = drz(c[q]) @ SX_MAT @ rz(b[q]) @ SX_MAT @ rz(a[q])
        uc = list(u); uc[q] = du
        derivs.append((6 + q, kron3(*uc)))

    return mat, derivs

# ---------------------------------------------------------------------------
# Cost + gradient via adjoint method
# ---------------------------------------------------------------------------

def cost_and_grad(params, target_dag):
    """Return (cost, gradient) where cost = 1 - process_fidelity."""
    factors = []
    all_derivs = []       # (factor_idx, global_param_idx, dmat_8x8)
    idx = 0

    for _ in range(N_LAYERS):
        # SQ layer
        sq_mat, sq_dv = _build_sq(params[idx:idx + 9])
        fi = len(factors)
        factors.append(sq_mat)
        for li, dm in sq_dv:
            all_derivs.append((fi, idx + li, dm))
        idx += 9

        # XXPlusYY on (0,1)
        t, bt = params[idx], params[idx + 1]
        fi = len(factors)
        factors.append(np.kron(xxp(t, bt), I2))
        all_derivs.append((fi, idx,     np.kron(dxxp_dt(t, bt), I2)))
        all_derivs.append((fi, idx + 1, np.kron(dxxp_db(t, bt), I2)))
        idx += 2

        # XXPlusYY on (1,2)
        t, bt = params[idx], params[idx + 1]
        fi = len(factors)
        factors.append(np.kron(I2, xxp(t, bt)))
        all_derivs.append((fi, idx,     np.kron(I2, dxxp_dt(t, bt))))
        all_derivs.append((fi, idx + 1, np.kron(I2, dxxp_db(t, bt))))
        idx += 2

    # Final SQ layer
    sq_mat, sq_dv = _build_sq(params[idx:idx + 9])
    fi = len(factors)
    factors.append(sq_mat)
    for li, dm in sq_dv:
        all_derivs.append((fi, idx + li, dm))

    K = len(factors)

    # Forward pass: R[j] = F_j @ F_{j-1} @ ... @ F_0
    R = [None] * K
    R[0] = factors[0]
    for j in range(1, K):
        R[j] = factors[j] @ R[j - 1]

    # f = Tr(target_dag @ U), cost = 1 - |f|^2 / d^2
    f = np.trace(target_dag @ R[K - 1])
    cost = 1.0 - (np.abs(f) ** 2) / (DIM * DIM)

    # Backward pass: L[j] = target_dag @ F_{K-1} @ ... @ F_{j+1}
    L = [None] * K
    L[K - 1] = target_dag
    for j in range(K - 2, -1, -1):
        L[j] = L[j + 1] @ factors[j + 1]

    # Gradient: dcost/dp_i = -(2/d^2) Re(f* Tr(R_{j-1} @ L_j @ dF_j))
    grad = np.zeros(len(params))
    f_conj = np.conj(f)
    scale = -2.0 / (DIM * DIM)

    cur_fi = -1
    A_T = None
    for fi_d, pi, dm in all_derivs:
        if fi_d != cur_fi:
            cur_fi = fi_d
            Rjm1 = R[fi_d - 1] if fi_d > 0 else I8
            A_T = (Rjm1 @ L[fi_d]).T      # Tr(A @ dm) = sum(A.T * dm)
        grad[pi] += scale * (f_conj * np.sum(A_T * dm)).real

    return cost, grad

# ---------------------------------------------------------------------------
# Gradient sanity check
# ---------------------------------------------------------------------------

def check_gradient(target_dag):
    rng = np.random.RandomState(99)
    x = rng.randn(TOTAL_PARAMS) * 0.5
    _, g = cost_and_grad(x, target_dag)
    eps = 1e-7
    ok = True
    for _ in range(8):
        i = rng.randint(TOTAL_PARAMS)
        xp = x.copy(); xp[i] += eps
        xm = x.copy(); xm[i] -= eps
        fd = (cost_and_grad(xp, target_dag)[0] - cost_and_grad(xm, target_dag)[0]) / (2 * eps)
        denom = max(abs(g[i]), abs(fd), 1e-12)
        if abs(fd - g[i]) / denom > 1e-4:
            print(f"  GRAD CHECK FAIL param {i}: analytic={g[i]:.6e} fd={fd:.6e}")
            ok = False
    if ok:
        print("  Gradient check passed.")

# ---------------------------------------------------------------------------
# Gate extraction
# ---------------------------------------------------------------------------

def extract_gates(params):
    gates = []
    idx = 0
    for _ in range(N_LAYERS):
        p = params[idx:idx + 9]
        a, b, c = p[0:3], p[3:6], p[6:9]
        for q in range(3):
            gates.append({"name": "rz", "params": [float(a[q])], "qubits": [q]})
        for q in range(3):
            gates.append({"name": "sx", "params": [], "qubits": [q]})
        for q in range(3):
            gates.append({"name": "rz", "params": [float(b[q])], "qubits": [q]})
        for q in range(3):
            gates.append({"name": "sx", "params": [], "qubits": [q]})
        for q in range(3):
            gates.append({"name": "rz", "params": [float(c[q])], "qubits": [q]})
        idx += 9

        gates.append({
            "name": "xxplusyy",
            "params": [float(params[idx]), float(params[idx + 1])],
            "qubits": [0, 1],
        })
        idx += 2
        gates.append({
            "name": "xxplusyy",
            "params": [float(params[idx]), float(params[idx + 1])],
            "qubits": [1, 2],
        })
        idx += 2

    # Final SQ layer
    p = params[idx:idx + 9]
    a, b, c = p[0:3], p[3:6], p[6:9]
    for q in range(3):
        gates.append({"name": "rz", "params": [float(a[q])], "qubits": [q]})
    for q in range(3):
        gates.append({"name": "sx", "params": [], "qubits": [q]})
    for q in range(3):
        gates.append({"name": "rz", "params": [float(b[q])], "qubits": [q]})
    for q in range(3):
        gates.append({"name": "sx", "params": [], "qubits": [q]})
    for q in range(3):
        gates.append({"name": "rz", "params": [float(c[q])], "qubits": [q]})
    return gates

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    target = get_target_unitary()
    target_dag = target.conj().T

    print(f"Ansatz: {N_LAYERS} layers, {TOTAL_PARAMS} params, "
          f"{N_LAYERS * 2} XXPlusYY gates")
    check_gradient(target_dag)
    print("Starting multi-restart L-BFGS-B...\n")

    rng = np.random.RandomState(42)
    best_cost = 1.0
    best_params = None
    t0 = time.time()

    for trial in range(600):
        elapsed = time.time() - t0
        if elapsed > 2400:
            print(f"Time budget at trial {trial} ({elapsed:.0f}s)")
            break

        # Vary initialisation scale
        r = trial % 5
        if r == 0:
            x0 = rng.uniform(-np.pi, np.pi, TOTAL_PARAMS)
        elif r == 1:
            x0 = rng.randn(TOTAL_PARAMS) * 0.3
        elif r == 2:
            x0 = rng.randn(TOTAL_PARAMS) * 1.0
        elif r == 3:
            x0 = rng.randn(TOTAL_PARAMS) * 2.0
        else:
            x0 = rng.randn(TOTAL_PARAMS) * np.pi

        try:
            res = minimize(
                cost_and_grad, x0, args=(target_dag,),
                method="L-BFGS-B", jac=True,
                options={"maxiter": 4000, "ftol": 1e-16, "gtol": 1e-15},
            )
        except Exception:
            continue

        if np.isnan(res.fun):
            continue

        if res.fun < best_cost:
            best_cost = res.fun
            best_params = res.x.copy()
            print(f"  T{trial:3d}: F={1 - res.fun:.15f}  "
                  f"(cost={res.fun:.3e}, t={time.time() - t0:.0f}s)")

        if best_cost < 1e-13:
            print(f"  Converged at trial {trial}!")
            break

    # Polish best solution
    if best_params is not None and best_cost > 1e-14:
        print("\nPolishing...")
        for _ in range(5):
            try:
                res = minimize(
                    cost_and_grad, best_params, args=(target_dag,),
                    method="L-BFGS-B", jac=True,
                    options={"maxiter": 15000, "ftol": 1e-17, "gtol": 1e-16},
                )
                if res.fun < best_cost:
                    best_cost = res.fun
                    best_params = res.x.copy()
                    print(f"  Polish: F={1 - res.fun:.15f}")
            except Exception:
                pass

    fidelity = 1.0 - best_cost
    print(f"\nFinal fidelity: {fidelity:.15f}")
    print(f"Total time: {time.time() - t0:.1f}s")

    if fidelity < 1.0 - 1e-6:
        print(f"WARNING: fidelity below threshold!")

    # Save results
    gates = extract_gates(best_params)
    xxcount = sum(1 for g in gates if g["name"] == "xxplusyy")

    os.makedirs("/app/result", exist_ok=True)

    with open("/app/result/circuit.json", "w") as f:
        json.dump({"num_qubits": 3, "gates": gates}, f, indent=2)

    with open("/app/result/metrics.json", "w") as f:
        json.dump({
            "xxplusyy_count": xxcount,
            "total_gates": len(gates),
            "process_fidelity": fidelity,
        }, f, indent=2)

    print(f"\nXXPlusYY: {xxcount}  Total: {len(gates)}")
    print("Done.")


if __name__ == "__main__":
    main()
