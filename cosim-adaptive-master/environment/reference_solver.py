"""
Monolithic reference solver for the PI-controlled DC electric drive.

Integrates the full coupled ODE system with high-accuracy RK4 (h=1e-4)
to produce a ground-truth trajectory for validation of co-simulation results.

Uses only Python standard library (no numpy dependency).

"""


def generate_reference(h=1e-4, t_end=1.0):
    """Generate reference solution using monolithic RK4 integration.

    Returns:
        ref_t: list of time points
        ref_w: list of load angular velocity values
    """
    # PI controller parameters
    k_pi = 0.1
    T_pi = 0.005

    # Motor parameters
    Ra = 0.05
    La = 0.0015
    ke = 0.6273
    kt = 0.6273

    # Mechanical parameters
    Jr = 0.001
    J = 1.0
    ratio = 10.0
    Jl_eff = Jr * ratio ** 2 + J  # 1.1

    def w_desired(t):
        return 10.0 if t >= 0.1 else 0.0

    def tau_ext(t):
        return 3.0 if t >= 0.5 else 0.0

    def rhs(t, y):
        x_i, ia, wl = y[0], y[1], y[2]
        wd = w_desired(t)
        te = tau_ext(t)
        e = wd - wl
        V = k_pi * e + (k_pi / T_pi) * x_i
        dx_i = e
        dia = (V - Ra * ia - ke * ratio * wl) / La
        dwl = (kt * ia / ratio - te) / Jl_eff
        return [dx_i, dia, dwl]

    n_steps = int(round(t_end / h))
    y = [0.0, 0.0, 0.0]

    results_t = [0.0]
    results_w = [0.0]

    for i in range(n_steps):
        t = i * h
        rk1 = rhs(t, y)
        y2 = [y[j] + h / 2 * rk1[j] for j in range(3)]
        rk2 = rhs(t + h / 2, y2)
        y3 = [y[j] + h / 2 * rk2[j] for j in range(3)]
        rk3 = rhs(t + h / 2, y3)
        y4 = [y[j] + h * rk3[j] for j in range(3)]
        rk4 = rhs(t + h, y4)
        y = [y[j] + h / 6 * (rk1[j] + 2 * rk2[j] + 2 * rk3[j] + rk4[j])
             for j in range(3)]
        results_t.append((i + 1) * h)
        results_w.append(y[2])

    return results_t, results_w


if __name__ == '__main__':
    import csv
    ref_t, ref_w = generate_reference()
    with open('reference_solution.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['time', 'w'])
        for t, w in zip(ref_t, ref_w):
            writer.writerow([f'{t:.10g}', f'{w:.10g}'])
    print(f"Reference solution written: {len(ref_t)} points")
