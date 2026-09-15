"""
Hydropower waterway simulation library.

Implements four components from the OpenHPL Modelica library:
1. Darcy friction factor (laminar/transition/turbulent)
2. Elastic penstock KP07 finite volume simulation
3. Bollrich gate discharge
4. Francis turbine Euler power
"""
import math
import numpy as np

PI = math.pi


# ==================== Helpers ====================

def _generalized_minmod(a, b, c):
    """Generalized minmod slope limiter."""
    if a > 0 and b > 0 and c > 0:
        return min(a, b, c)
    elif a < 0 and b < 0 and c < 0:
        return max(a, b, c)
    return 0.0


# ==================== Darcy Friction ====================

def darcy_friction(Re, D, eps):
    """
    Compute Darcy friction factor for pipe flow.

    Three regimes:
    - Laminar (Re < 2100): fD = 64/Re
    - Turbulent (Re > 2300): Swamee-Jain approximation
    - Transition (2100 <= Re <= 2300): C1 cubic Hermite interpolation
    """
    if Re <= 0:
        return 0.0

    Re_lam = 2100.0
    Re_turb = 2300.0

    if Re < Re_lam:
        return 64.0 / Re

    if Re > Re_turb:
        term = eps / (3.7 * D) + 5.74 / Re**0.9
        return 1.0 / (2.0 * math.log10(term))**2

    # Transition zone: cubic Hermite interpolation
    # Values at boundaries
    f0 = 64.0 / Re_lam

    term_t = eps / (3.7 * D) + 5.74 / Re_turb**0.9
    log_t = math.log10(term_t)
    f1 = 1.0 / (2.0 * log_t)**2

    # Derivatives at boundaries
    df0 = -64.0 / Re_lam**2

    # d/dRe of Swamee-Jain at Re_turb
    dterm_dRe = -0.9 * 5.74 / Re_turb**1.9
    # d/dRe of 1/(2*log10(term))^2
    # Let g = 2*log10(term), fD = 1/g^2
    # dfD/dRe = -2/g^3 * dg/dRe = -2/g^3 * 2/(term*ln(10)) * dterm/dRe
    g_val = 2.0 * log_t
    df1 = -2.0 / g_val**3 * (2.0 / (term_t * math.log(10.0))) * dterm_dRe

    # Hermite basis on t in [0, 1]
    dRe = Re_turb - Re_lam  # = 200
    t = (Re - Re_lam) / dRe
    t2 = t * t
    t3 = t2 * t

    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2

    return h00 * f0 + h10 * dRe * df0 + h01 * f1 + h11 * dRe * df1


def friction_force(v, D, L, rho, mu, eps):
    """
    Compute Darcy-Weisbach pipe friction force.

    F_f = (pi/8) * fD * rho * L * D * v * |v|
    """
    Re = rho * abs(v) * D / mu
    fD = darcy_friction(Re, D, eps)
    return PI / 8.0 * fD * rho * L * D * v * abs(v)


# ==================== Elastic Penstock (KP07) ====================

class ElasticPenstock:
    """
    Elastic penstock model using KP07 central-upwind finite volume scheme.

    Solves coupled pressure-mass flow rate hyperbolic PDEs with
    compressible water and elastic pipe walls.
    """

    def __init__(self, L, H, D_i, D_o=None, N=20, rho=999.65, mu=1.3076e-3,
                 beta=4.5e-10, beta_total=None, p_eps=0.0, p_a=0.0, g=9.81,
                 theta=1.3):
        if D_o is None:
            D_o = D_i
        if beta_total is None:
            beta_total = 1.0 / (rho * 1e6)

        self.L = L
        self.H = H
        self.D_i = D_i
        self.D_o = D_o
        self.N = N
        self.rho = rho
        self.mu = mu
        self.beta = beta
        self.beta_total = beta_total
        self.p_eps = p_eps
        self.p_a = p_a
        self.g = g
        self.theta = theta
        self.dx = L / N

        # Diameter arrays (centered and at cell boundaries)
        dD = (D_i - D_o) / N
        self.D_center = np.linspace(D_i - dD / 2, D_o + dD / 2, N)
        self.D_boundary = np.linspace(D_i, D_o, N + 1)

        # Cross-section areas at atmospheric pressure
        self.A_atm_c = PI / 4 * self.D_center**2
        self.A_atm_b = PI / 4 * self.D_boundary**2

    def simulate(self, t_end, dt, p_inlet_func, mdot_outlet_func, Vdot_0=0.0):
        """
        Time-integrate elastic penstock flow using RK4.

        Parameters
        ----------
        t_end : float — simulation end time [s]
        dt : float — time step [s]
        p_inlet_func : callable(t) -> float — inlet pressure [Pa]
        mdot_outlet_func : callable(t) -> float — outlet mass flow [kg/s]
        Vdot_0 : float — initial volume flow rate [m³/s]

        Returns
        -------
        dict with keys 'times', 'pressures', 'flows'
        """
        N = self.N
        rho0 = self.rho

        mdot_0 = rho0 * Vdot_0

        # Initial pressure: hydrostatic gradient
        dp = rho0 * self.g * self.H / N
        p_inlet_0 = p_inlet_func(0.0)
        p0 = np.array([p_inlet_0 + dp * (k + 0.5) for k in range(N)])

        # State vector: U = [p_0..p_{N-1}, mdot_0..mdot_{N-1}]
        U = np.zeros(2 * N)
        U[:N] = p0
        U[N:] = mdot_0

        times = [0.0]
        pressures = [U[:N].copy()]
        flows = [U[N:].copy()]

        t = 0.0
        while t < t_end - dt / 2:
            # RK4 time integration
            p_in = p_inlet_func(t)
            mdot_out = mdot_outlet_func(t)
            k1 = self._rhs(U, p_in, mdot_out)

            t_h = t + dt / 2
            p_in_h = p_inlet_func(t_h)
            mdot_out_h = mdot_outlet_func(t_h)
            k2 = self._rhs(U + dt / 2 * k1, p_in_h, mdot_out_h)
            k3 = self._rhs(U + dt / 2 * k2, p_in_h, mdot_out_h)

            t_e = t + dt
            p_in_e = p_inlet_func(t_e)
            mdot_out_e = mdot_outlet_func(t_e)
            k4 = self._rhs(U + dt * k3, p_in_e, mdot_out_e)

            U = U + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)

            t += dt
            times.append(t)
            pressures.append(U[:N].copy())
            flows.append(U[N:].copy())

        return {
            'times': np.array(times),
            'pressures': np.array(pressures),
            'flows': np.array(flows),
        }

    def _compute_slopes(self, vals_ext, N, dx, theta):
        """Compute minmod-limited slopes for N cells from ghost-padded array."""
        slopes = np.zeros(N)
        for j in range(N):
            je = j + 2  # index in extended array
            a = theta * (vals_ext[je] - vals_ext[je - 1]) / dx
            b = (vals_ext[je + 1] - vals_ext[je - 1]) / (2 * dx)
            c = theta * (vals_ext[je + 1] - vals_ext[je]) / dx
            slopes[j] = _generalized_minmod(a, b, c)
        return slopes

    def _rhs(self, U, p_inlet, mdot_outlet):
        """Compute dU/dt using the KP07 central-upwind scheme."""
        N = self.N
        dx = self.dx
        rho0 = self.rho
        beta = self.beta
        bt = self.beta_total
        pa = self.p_a
        theta = self.theta

        pp = U[:N]  # pressure
        mm = U[N:]  # mass flow rate

        # === Centered derived quantities ===
        Fap_c = rho0 * self.A_atm_c * (1 + bt * (pp - pa))
        rho_c = rho0 * (1 + beta * (pp - pa))
        A_c = Fap_c / rho_c
        v_c = mm / np.where(np.abs(Fap_c) > 1e-30, Fap_c, 1e-30)

        # === Ghost cells (zero-gradient extrapolation) ===
        p_ext = np.empty(N + 4)
        p_ext[0] = pp[0]
        p_ext[1] = pp[0]
        p_ext[2:N + 2] = pp
        p_ext[N + 2] = pp[N - 1]
        p_ext[N + 3] = pp[N - 1]

        m_ext = np.empty(N + 4)
        m_ext[0] = mm[0]
        m_ext[1] = mm[0]
        m_ext[2:N + 2] = mm
        m_ext[N + 2] = mm[N - 1]
        m_ext[N + 3] = mm[N - 1]

        # === Slopes via generalized minmod limiter ===
        p_slopes = self._compute_slopes(p_ext, N, dx, theta)
        m_slopes = self._compute_slopes(m_ext, N, dx, theta)

        # === Piecewise linear reconstruction at interfaces ===
        # Right interface of cell j (j+1/2):
        # U^-_{j+1/2} = U_j + dx/2 * s_j  (from cell j)
        p_mR = pp + dx / 2 * p_slopes
        m_mR = mm + dx / 2 * m_slopes

        # U^+_{j+1/2} = U_{j+1} - dx/2 * s_{j+1}  (from cell j+1)
        p_pR = np.empty(N)
        m_pR = np.empty(N)
        p_pR[:N - 1] = pp[1:] - dx / 2 * p_slopes[1:]
        m_pR[:N - 1] = mm[1:] - dx / 2 * m_slopes[1:]
        # Right boundary: extrapolate pressure, BC for mdot
        p_pR[N - 1] = pp[N - 1]
        m_pR[N - 1] = mdot_outlet  # <-- BC override

        # Left interface of cell j (j-1/2):
        # U^+_{j-1/2} = U_j - dx/2 * s_j  (from cell j)
        p_pL = pp - dx / 2 * p_slopes
        m_pL = mm - dx / 2 * m_slopes

        # U^-_{j-1/2} = U_{j-1} + dx/2 * s_{j-1}  (from cell j-1)
        p_mL = np.empty(N)
        m_mL = np.empty(N)
        p_mL[1:] = pp[:N - 1] + dx / 2 * p_slopes[:N - 1]
        m_mL[1:] = mm[:N - 1] + dx / 2 * m_slopes[:N - 1]
        # Left boundary: BC for pressure, extrapolate mdot
        p_mL[0] = p_inlet  # <-- BC override
        m_mL[0] = mm[0]

        # === A_atm at interfaces ===
        A_atm_R = self.A_atm_b[1:]   # right interfaces (N values)
        A_atm_L = self.A_atm_b[:-1]  # left interfaces (N values)

        # === Derived quantities at interface positions ===
        def _derived(p, m, A_atm_i):
            rho_i = rho0 * (1 + beta * (p - pa))
            Fap_i = rho0 * A_atm_i * (1 + bt * (p - pa))
            A_i = Fap_i / rho_i
            Fap_safe = np.where(np.abs(Fap_i) > 1e-30, Fap_i, 1e-30)
            v_i = m / Fap_safe
            return Fap_i, rho_i, A_i, v_i

        Fap_mR, _, A_mR, v_mR = _derived(p_mR, m_mR, A_atm_R)
        Fap_pR, _, A_pR, v_pR = _derived(p_pR, m_pR, A_atm_R)
        Fap_mL, _, A_mL, v_mL = _derived(p_mL, m_mL, A_atm_L)
        Fap_pL, _, A_pL, v_pL = _derived(p_pL, m_pL, A_atm_L)

        # === Eigenvalues (wave speeds) ===
        def _eigvals(v, A, A_atm_i):
            disc = v**2 + 4 * A / (rho0 * A_atm_i * bt)
            sq = np.sqrt(np.maximum(disc, 0))
            return (v + sq) / 2, (v - sq) / 2

        l1_mR, l2_mR = _eigvals(v_mR, A_mR, A_atm_R)
        l1_pR, l2_pR = _eigvals(v_pR, A_pR, A_atm_R)
        l1_mL, l2_mL = _eigvals(v_mL, A_mL, A_atm_L)
        l1_pL, l2_pL = _eigvals(v_pL, A_pL, A_atm_L)

        # === One-sided local speed propagation ===
        # Right interface
        a_mp = np.minimum(np.minimum(l2_pR, l2_mR), 0)  # min eigenvalue, clamped ≤ 0
        a_pp = np.maximum(np.maximum(l1_pR, l1_mR), 0)  # max eigenvalue, clamped ≥ 0
        # Left interface
        a_mm = np.minimum(np.minimum(l2_pL, l2_mL), 0)
        a_pm = np.maximum(np.maximum(l1_pL, l1_mL), 0)

        # === Flux vectors ===
        def _flux(m, v, A, p, A_atm_i):
            f1 = m / (rho0 * A_atm_i * bt)     # pressure eq flux
            f2 = m * v + A * p                   # momentum eq flux
            return f1, f2

        f1_mR, f2_mR = _flux(m_mR, v_mR, A_mR, p_mR, A_atm_R)
        f1_pR, f2_pR = _flux(m_pR, v_pR, A_pR, p_pR, A_atm_R)
        f1_mL, f2_mL = _flux(m_mL, v_mL, A_mL, p_mL, A_atm_L)
        f1_pL, f2_pL = _flux(m_pL, v_pL, A_pL, p_pL, A_atm_L)

        # === Central-upwind numerical fluxes ===
        eps_s = 1e-30  # prevent division by zero

        den_R = a_pp - a_mp + eps_s
        Hp1 = (a_pp * f1_mR - a_mp * f1_pR) / den_R + \
              a_pp * a_mp / den_R * (p_pR - p_mR)
        Hp2 = (a_pp * f2_mR - a_mp * f2_pR) / den_R + \
              a_pp * a_mp / den_R * (m_pR - m_mR)

        den_L = a_pm - a_mm + eps_s
        Hm1 = (a_pm * f1_mL - a_mm * f1_pL) / den_L + \
              a_pm * a_mm / den_L * (p_pL - p_mL)
        Hm2 = (a_pm * f2_mL - a_mm * f2_pL) / den_L + \
              a_pm * a_mm / den_L * (m_pL - m_mL)

        # === Friction force per cell (source term) ===
        F_f = np.zeros(N)
        for i in range(N):
            D_eff = 2 * math.sqrt(A_c[i] / PI)
            F_f[i] = friction_force(
                v_c[i], D_eff, dx, rho_c[i], self.mu, self.p_eps) / dx

        # === Source terms ===
        S_p = np.zeros(N)                              # pressure: no source
        S_m = Fap_c * self.g * self.H / self.L - F_f  # momentum: gravity - friction

        # === Semi-discrete RHS: dU/dt = -(H_R - H_L)/dx + S ===
        dU = np.zeros(2 * N)
        dU[:N] = -(Hp1 - Hm1) / dx + S_p
        dU[N:] = -(Hp2 - Hm2) / dx + S_m

        return dU


# ==================== Gate Discharge (Bollrich) ====================

def gate_discharge(gate_type, a, h_0, h_2, b, g=9.81, rho=999.65,
                   r=None, h_h=None):
    """
    Gate discharge using Bollrich (2019) equations.

    Parameters
    ----------
    gate_type : str — 'sluice' or 'radial'
    a : float — gate opening [m]
    h_0 : float — upstream water level [m]
    h_2 : float — downstream water level [m]
    b : float — gate width [m]
    r : float — arm radius (radial gate) [m]
    h_h : float — hinge height above bottom (radial gate) [m]

    Returns
    -------
    float — volume flow rate [m³/s]
    """
    # Contraction coefficient
    if gate_type == 'sluice':
        psi = 1.0 / (1.0 + 0.64 * math.sqrt(1.0 - (a / h_0)**2))
    else:  # radial
        alpha_rad = PI / 2 - math.asin((h_h - a) / r)
        alpha_deg = math.degrees(alpha_rad)
        psi = 1.3 - 0.8 * math.sqrt(1.0 - ((alpha_deg - 205.0) / 220.0)**2)

    # Discharge coefficient
    mu_A = psi / math.sqrt(1 + psi * a / h_0)

    # Gate opening area
    A = a * b

    # Free-flow limit for downstream level
    h2_limit = a * psi / 2 * (
        math.sqrt(1 + 16 / (psi * (1 + psi * a / h_0)) * (h_0 / a)) - 1)

    # Back-up coefficient
    if h_2 >= h2_limit:
        # Backed-up (submerged) flow
        t1 = 1 + psi * a / h_0
        t2 = 1 - 2 * psi * a / h_0 * (1 - psi * a / max(1e-30, h_2))
        inner = t2**2 + (h_2 / h_0)**2 - 1
        chi = math.sqrt(t1 * (t2 - math.sqrt(max(inner, 0))))
    else:
        chi = 1.0  # free flow

    return chi * mu_A * A * math.sqrt(2 * g * h_0)


# ==================== Francis Turbine ====================

def francis_power(mdot, omega, R_1, R_2, w_1, alpha1_deg, beta2_deg,
                  D_i, rho):
    """
    Francis turbine shaft power from Euler turbomachinery equation.

    Parameters
    ----------
    mdot : float — mass flow rate [kg/s]
    omega : float — angular velocity [rad/s]
    R_1, R_2 : float — inlet/outlet runner radii [m]
    w_1 : float — inlet runner width [m]
    alpha1_deg : float — guide vane angle [degrees]
    beta2_deg : float — outlet blade angle [degrees]
    D_i : float — inlet pipe diameter [m]
    rho : float — water density [kg/m³]

    Returns
    -------
    float — shaft power [W]
    """
    Vdot = mdot / rho

    # Cross-section areas
    A_1 = 2 * PI * R_1 * w_1
    A_2 = PI * R_2**2

    # Cotangents of angles
    alpha1 = math.radians(alpha1_deg)
    beta2 = math.radians(beta2_deg)
    cot_a1 = 1.0 / math.tan(alpha1)
    cot_b2 = 1.0 / math.tan(beta2)

    # Euler equation: Wdot_s = W_t1 - W_t2
    W_t1 = mdot * omega * R_1 * (Vdot / A_1) * cot_a1
    W_t2 = mdot * omega * R_2 * (omega * R_2 + (Vdot / A_2) * cot_b2)

    return W_t1 - W_t2
