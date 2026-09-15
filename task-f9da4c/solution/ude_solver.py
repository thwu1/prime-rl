#!/usr/bin/env python3
"""
Solution for thermal model correction task.

Reads HDF5 reference data and YAML config, interfaces with the compiled
C library to observe model discrepancy, then builds a corrected model
using a neural-network-augmented ODE (UDE), trains it, and recovers
the missing physics via curve fitting.
"""

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import minimize, curve_fit
import h5py
import yaml
import ctypes
import os
import sys

# ========== Load configuration from YAML ==========
with open('/app/config.yaml') as f:
    config = yaml.safe_load(f)

C2 = config['system']['pot_heat_capacity']        # 15.0
G_air = config['system']['air_conductance']        # 0.1
T_env = config['system']['environment_temperature'] # 293.15
T0 = config['system']['initial_temperature']        # 273.15

# ========== Load reference data from HDF5 ==========
with h5py.File('/app/data/measurements.h5', 'r') as f:
    t_train_full = f['training/time'][:]
    T_pot_ref_full = f['training/temperature'][:]
    t_extrap = f['extrapolation/time'][:]

print(f"Loaded {len(t_train_full)} training points from HDF5")
print(f"Reference T range: [{T_pot_ref_full.min():.4f}, {T_pot_ref_full.max():.4f}] K")
sys.stdout.flush()

# ========== Interface with compiled C model to observe discrepancy ==========
lib = ctypes.CDLL('/app/lib/thermal_model.so')
lib.thermal_simulate.restype = ctypes.c_int
lib.thermal_simulate.argtypes = [
    ctypes.POINTER(ctypes.c_double), ctypes.c_int,
    ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double,
    ctypes.POINTER(ctypes.c_double)
]
lib.get_input_heat.restype = ctypes.c_double
lib.get_input_heat.argtypes = [ctypes.c_double]

n_pts = len(t_train_full)
c_t = (ctypes.c_double * n_pts)(*t_train_full)
c_T = (ctypes.c_double * n_pts)()
ret = lib.thermal_simulate(c_t, n_pts, C2, G_air, T_env, T0, c_T)
assert ret == 0, "C library simulation failed"
T_incomplete = np.array([c_T[i] for i in range(n_pts)])

discrepancy = T_pot_ref_full - T_incomplete
print(f"Incomplete model max error: {np.max(np.abs(discrepancy)):.4f} K")
print(f"Incomplete model T range: [{T_incomplete.min():.4f}, {T_incomplete.max():.4f}] K")
print(f"The incomplete model consistently {'under' if discrepancy.mean() < 0 else 'over'}estimates.")
sys.stdout.flush()

# ========== Subsample for faster training ==========
t_train = t_train_full[::5]   # 100 points
T_pot_ref = T_pot_ref_full[::5]

T_RANGE = 10.0


def input_f(t):
    return (1 + np.sin(0.005 * t**2)) / 2


# ========== Neural Network ==========

def silu(x):
    """SiLU activation with overflow-safe sigmoid computation."""
    x_clip = np.clip(x, -500, 500)
    sigmoid = np.where(x_clip >= 0,
                       1.0 / (1.0 + np.exp(-x_clip)),
                       np.exp(x_clip) / (1.0 + np.exp(x_clip)))
    return x * sigmoid


def init_params(seed=42):
    rng = np.random.RandomState(seed)
    W1 = rng.randn(4, 2) * 0.5
    b1 = np.zeros(4)
    W2 = rng.randn(1, 4) * 1e-3
    b2 = np.zeros(1)
    log_C = np.array([0.0])
    return np.concatenate([W1.ravel(), b1, W2.ravel(), b2, log_C])


def unpack(theta):
    return (theta[0:8].reshape(4, 2), theta[8:12],
            theta[12:16].reshape(1, 4), theta[16:17], theta[17])


def nn_forward(x_in, W1, b1, W2, b2):
    return (W2 @ silu(W1 @ x_in + b1) + b2)[0]


# ========== ODE with custom RK4 (fast for training) ==========

def rk4_solve(t_eval, W1, b1, W2, b2, C_nn):
    """Fixed-step RK4 on the given time grid."""
    n = len(t_eval)
    ys = np.zeros((n, 2))
    ys[0] = [T0, T0]

    def rhs(t, y):
        x, T2 = y
        Q_in = input_f(t)
        Q_nn = nn_forward(np.array([(x - T0) / T_RANGE, (T2 - T0) / T_RANGE]),
                          W1, b1, W2, b2)
        return np.array([(Q_in - Q_nn) / C_nn,
                         (Q_nn - G_air * (T2 - T_env)) / C2])

    for i in range(n - 1):
        dt = t_eval[i + 1] - t_eval[i]
        ti, yi = t_eval[i], ys[i]
        k1 = rhs(ti, yi)
        k2 = rhs(ti + dt / 2, yi + dt / 2 * k1)
        k3 = rhs(ti + dt / 2, yi + dt / 2 * k2)
        k4 = rhs(ti + dt, yi + dt * k3)
        ys[i + 1] = yi + (dt / 6) * (k1 + 2 * k2 + 2 * k3 + k4)
    return ys


def scipy_solve(theta, t_eval):
    """Accurate solve via scipy (for final predictions)."""
    W1, b1, W2, b2, log_C = unpack(theta)
    C_nn = np.exp(np.clip(log_C, -5, 5))

    def rhs(t, y):
        x, T2 = y
        Q_in = input_f(t)
        Q_nn = nn_forward(np.array([(x - T0) / T_RANGE, (T2 - T0) / T_RANGE]),
                          W1, b1, W2, b2)
        return [(Q_in - Q_nn) / C_nn, (Q_nn - G_air * (T2 - T_env)) / C2]

    return solve_ivp(rhs, [t_eval[0], t_eval[-1]], [T0, T0],
                     t_eval=t_eval, method='RK45', rtol=1e-8, atol=1e-8)


# ========== Loss (uses fast RK4) ==========

def loss_fn(theta):
    W1, b1, W2, b2, log_C = unpack(theta)
    C_nn = np.exp(np.clip(log_C, -5, 5))
    try:
        ys = rk4_solve(t_train, W1, b1, W2, b2, C_nn)
        if np.any(np.isnan(ys)) or np.any(np.abs(ys) > 1e6):
            return 1e6
        return float(np.mean((ys[:, 1] - T_pot_ref) ** 2))
    except Exception:
        return 1e6


def grad_forward(theta, eps=1e-6):
    """Forward finite-difference gradient."""
    f0 = loss_fn(theta)
    g = np.zeros(len(theta))
    for i in range(len(theta)):
        tp = theta.copy()
        tp[i] += eps
        g[i] = (loss_fn(tp) - f0) / eps
    return g


# ========== Adam optimizer ==========

class Adam:
    def __init__(self, lr=5e-3):
        self.lr, self.b1, self.b2, self.eps = lr, 0.9, 0.999, 1e-8
        self.m = self.v = None
        self.t = 0

    def step(self, p, g):
        if self.m is None:
            self.m, self.v = np.zeros_like(p), np.zeros_like(p)
        self.t += 1
        self.m = self.b1 * self.m + (1 - self.b1) * g
        self.v = self.b2 * self.v + (1 - self.b2) * g ** 2
        mh = self.m / (1 - self.b1 ** self.t)
        vh = self.v / (1 - self.b2 ** self.t)
        return p - self.lr * mh / (np.sqrt(vh) + self.eps)


# ========== Training ==========

theta = init_params()
print(f"\nParams: {len(theta)}, training pts: {len(t_train)}")
print(f"Initial loss: {loss_fn(theta):.6e}")
sys.stdout.flush()

# Stage 1: Adam
print("\n=== Stage 1: Adam (300 iters) ===")
adam = Adam(lr=5e-3)
best_loss, best_theta = float('inf'), theta.copy()

for ep in range(300):
    g = grad_forward(theta)
    gn = np.linalg.norm(g)
    if gn > 10:
        g *= 10 / gn
    theta = adam.step(theta, g)
    if ep % 50 == 0:
        L = loss_fn(theta)
        _, _, _, _, lc = unpack(theta)
        print(f"  {ep:3d}: loss={L:.6e} C_nn={np.exp(lc):.3f}")
        sys.stdout.flush()
        if L < best_loss:
            best_loss, best_theta = L, theta.copy()

if loss_fn(best_theta) < loss_fn(theta):
    theta = best_theta
print(f"Adam done: {loss_fn(theta):.6e}")
sys.stdout.flush()

# Stage 2: L-BFGS-B
print("\n=== Stage 2: L-BFGS-B ===")
sys.stdout.flush()
res = minimize(loss_fn, theta, method='L-BFGS-B',
               options={'maxiter': 300, 'ftol': 1e-15, 'gtol': 1e-10})
theta = res.x
print(f"L-BFGS done: {loss_fn(theta):.6e} (converged={res.success})")
sys.stdout.flush()

# ========== Generate predictions ==========
os.makedirs('/app/results', exist_ok=True)

# Accurate predictions via scipy
sol_train = scipy_solve(theta, t_train_full)

# Full range for extrapolation
t_full = np.linspace(0, 200, 1000)
sol_full = scipy_solve(theta, t_full)
t_test_mask = sol_full.t >= 100.0
t_test_out = sol_full.t[t_test_mask]
T2_test_out = sol_full.y[1, t_test_mask]

# Save training predictions
with open('/app/results/predictions_train.csv', 'w') as f:
    f.write('t,T_pot_pred\n')
    for ti, Ti in zip(t_train_full, sol_train.y[1]):
        f.write(f'{ti:.10f},{Ti:.10f}\n')

# Save test predictions
with open('/app/results/predictions_test.csv', 'w') as f:
    f.write('t,T_pot_pred\n')
    for ti, Ti in zip(t_test_out, T2_test_out):
        f.write(f'{ti:.10f},{Ti:.10f}\n')

# Training loss on full set
final_loss = float(np.mean((sol_train.y[1] - T_pot_ref_full) ** 2))
with open('/app/results/training_loss.txt', 'w') as f:
    f.write(f'{final_loss}')

# Conservation check: energy balance residual
W1, b1, W2, b2, log_C = unpack(theta)
C_nn = np.exp(np.clip(log_C, -5, 5))
y_end = sol_train.y[:, -1]
Q_in_end = input_f(t_train_full[-1])
Q_nn_end = nn_forward(np.array([(y_end[0] - T0) / T_RANGE, (y_end[1] - T0) / T_RANGE]),
                       W1, b1, W2, b2)
dx_end = (Q_in_end - Q_nn_end) / C_nn
conservation_err = abs(dx_end * C_nn)
with open('/app/results/conservation_check.txt', 'w') as f:
    f.write(f'{conservation_err}')

# ========== Equation recovery via curve fitting ==========
print("\n=== Equation Recovery ===")

x1g = np.linspace(-2, 3, 80)
x2g = np.linspace(-2, 3, 80)
X1, X2 = np.meshgrid(x1g, x2g, indexing='ij')
X1f, X2f = X1.ravel(), X2.ravel()
nn_out = np.array([nn_forward(np.array([a, b]), W1, b1, W2, b2)
                    for a, b in zip(X1f, X2f)])


def lin_model(xy, a, b):
    return a * (xy[0] - xy[1]) + b


popt, _ = curve_fit(lin_model, (X1f, X2f), nn_out)
a_c, b_c = popt
G_disc = a_c / T_RANGE
ss_res = np.sum((nn_out - lin_model((X1f, X2f), *popt)) ** 2)
ss_tot = np.sum((nn_out - nn_out.mean()) ** 2)
r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

with open('/app/results/recovered_equation.txt', 'w') as f:
    f.write(f"Learned coupling (normalized inputs):\n")
    f.write(f"  Q(x_norm, T2_norm) = {a_c:.4f} * (x_norm - T2_norm) + ({b_c:.4f})\n\n")
    f.write(f"In physical coordinates:\n")
    f.write(f"  Q(x, T2) = {G_disc:.4f} * (x - T2) + ({b_c:.4f})\n\n")
    f.write(f"Discovered thermal conductance: G = {abs(G_disc):.4f}\n")
    f.write(f"Linear fit R^2 = {r2:.6f}\n")
    f.write(f"Learned hidden capacitance: C_nn = {C_nn:.4f}\n")

print(f"\n=== Summary ===")
print(f"Final MSE: {final_loss:.6e}")
print(f"C_nn: {C_nn:.4f}, G_disc: {abs(G_disc):.4f}, R^2: {r2:.4f}")
print(f"Conservation err: {conservation_err:.6e}")
print("Done.")
