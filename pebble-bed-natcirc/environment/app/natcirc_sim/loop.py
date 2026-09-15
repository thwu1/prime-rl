"""
Natural circulation loop solver for pebble-bed reactor.

Solves for the steady-state mass flow rate where the buoyancy
driving force balances the total frictional pressure losses
around the circulation loop.

Core packed-bed correlations are computed by the Fortran library
via fortran_bridge. Solver runtime options are read from the
SQLite database at /app/reactor.db.
"""
import sqlite3
import numpy as np
from . import helium, correlations, fortran_bridge

G_ACCEL = 9.80665  # m/s^2


def _load_solver_options(db_path='/app/reactor.db'):
    """Load solver runtime options from SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT key, value FROM solver_options")
    opts = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return opts


def solve_steady_state(Q_decay, T_inlet, pressure, config, n_nodes):
    """
    Solve for steady-state natural circulation conditions.

    Parameters
    ----------
    Q_decay : float
        Total decay heat power [W]
    T_inlet : float
        Core inlet temperature [K]
    pressure : float
        System pressure [Pa]
    config : dict
        Parsed reactor configuration
    n_nodes : int
        Number of axial discretization nodes

    Returns
    -------
    dict
        Results containing mass flow rate, temperatures, and pressure drop.
    """
    core = config['core']
    chimney = config['chimney']
    he_cfg = config['helium']
    gr_cfg = config['graphite']

    H = core['height_m']
    R = core['radius_m']
    d_p = core['pebble_diameter_m']
    eps = core['porosity']
    A_core = np.pi * R**2

    H_ch = chimney['height_m']
    A_ch = chimney['flow_area_m2']
    D_ch = chimney['hydraulic_diameter_m']
    f_ch = chimney['friction_factor']

    cp = he_cfg['cp']
    R_sp = he_cfg['R_specific']
    k_coeff = he_cfg['k_coeff']
    k_exp = he_cfg['k_exp']

    k_a = gr_cfg['k_a']
    k_b = gr_cfg['k_b']

    # Load solver runtime options from database
    solver_opts = _load_solver_options()
    use_chimney_buoy = solver_opts.get('include_chimney_buoyancy', 0) > 0
    max_iter = int(solver_opts.get('max_bisection_iter', 300))
    conv_tol = solver_opts.get('convergence_tol', 1e-12)
    max_temp = solver_opts.get('max_temperature_K', 5000)

    # Axial discretization (cell-centered)
    dz = H / n_nodes
    z = np.linspace(dz / 2, H - dz / 2, n_nodes)

    # Sinusoidal power profile
    q_peak = Q_decay * np.pi / (2.0 * A_core * H)
    q_profile = q_peak * np.sin(np.pi * z / H)

    rho_inlet = helium.density(T_inlet, pressure, R_sp)

    def momentum_balance(mdot):
        """Returns buoyancy minus total friction. Zero at equilibrium."""
        # Fluid temperature from energy balance
        T_f = T_inlet + (Q_decay / (2.0 * mdot * cp)) * (
            1.0 - np.cos(np.pi * z / H)
        )
        T_out = T_inlet + Q_decay / (mdot * cp)

        if T_out > max_temp:
            return 1e10

        rho_f = helium.density(T_f, pressure, R_sp)
        rho_out = helium.density(T_out, pressure, R_sp)

        # Buoyancy: density difference integrated over heated core
        buoyancy = G_ACCEL * np.sum((rho_inlet - rho_f) * dz)
        # Chimney/riser contribution (controlled by database flag)
        if use_chimney_buoy:
            buoyancy += G_ACCEL * H_ch * (rho_inlet - rho_out)

        # Core friction via Fortran Ergun correlation
        v_s = mdot / (rho_f * A_core)
        mu_f = np.vectorize(helium.viscosity)(T_f)
        dp_dz = fortran_bridge.ergun_pressure_gradient(
            rho_f, v_s, mu_f, d_p, eps
        )
        core_friction = np.sum(dp_dz * dz)

        # Chimney friction (Darcy-Weisbach)
        v_ch = mdot / (rho_out * A_ch)
        chimney_friction = correlations.darcy_weisbach_dp(
            f_ch, H_ch, D_ch, rho_out, v_ch
        )

        return buoyancy - core_friction - chimney_friction

    # Bisection solver for equilibrium mass flow rate
    lo, hi = 0.001, 200.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        if momentum_balance(mid) > 0:
            lo = mid
        else:
            hi = mid
        if (hi - lo) / mid < conv_tol:
            break

    mdot = (lo + hi) / 2.0

    # --- Post-processing with converged flow rate ---
    T_f = T_inlet + (Q_decay / (2.0 * mdot * cp)) * (
        1.0 - np.cos(np.pi * z / H)
    )
    T_out = T_inlet + Q_decay / (mdot * cp)

    rho_f = helium.density(T_f, pressure, R_sp)
    v_s = mdot / (rho_f * A_core)
    mu_f = np.vectorize(helium.viscosity)(T_f)
    k_f = helium.thermal_conductivity(T_f, k_coeff, k_exp)

    Pr = mu_f * cp / k_f
    Re = rho_f * v_s * d_p / mu_f

    Nu = fortran_bridge.wakao_kaguei_nusselt(Re, Pr)
    h_conv = Nu * k_f / d_p
    h_vol = 6.0 * (1.0 - eps) * h_conv / d_p

    # Pebble surface temperature
    T_surf = T_f + q_profile / h_vol

    # Pebble centerline temperature (analytical solution for sphere
    # with temperature-dependent conductivity k(T) = 1/(k_a + k_b*T))
    r_p = d_p / 2.0
    q_peb = q_profile / (1.0 - eps)
    integral_k = q_peb * r_p**2 / 6.0
    T_center = ((k_a + k_b * T_surf) * np.exp(k_b * integral_k) - k_a) / k_b

    # Recompute core pressure drop for output
    dp_dz = fortran_bridge.ergun_pressure_gradient(rho_f, v_s, mu_f, d_p, eps)
    core_dp = float(np.sum(dp_dz * dz))

    return {
        'mdot': float(mdot),
        'T_out': float(T_out),
        'peak_T_surf': float(np.max(T_surf)),
        'peak_T_center': float(np.max(T_center)),
        'core_dp': core_dp,
    }
