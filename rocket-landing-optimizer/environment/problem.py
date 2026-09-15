import numpy as np

# ============================================================
# Powered Descent Guidance — Problem Definition
# ============================================================
# 2D rocket landing with mass depletion.
#
# State:   x = [rx, ry, vx, vy, z]   where z = ln(mass)
# Control: u = [Tx, Ty]              thrust force vector
#
# Dynamics:
#   drx/dt = vx
#   dry/dt = vy
#   dvx/dt = Tx * exp(-z)            thrust acceleration
#   dvy/dt = Ty * exp(-z) - g0       thrust accel minus gravity
#   dz/dt  = -alpha_m * ||u|| * exp(-z)   mass depletion
# ============================================================

# Gravitational acceleration (normalized)
g0 = 1.0

# Mass parameters
m_wet = 2.0      # initial (wet) mass
m_dry = 0.5      # dry mass (structure only)

# Thrust limits
T_min = 0.5      # minimum thrust magnitude — engines cannot throttle below this
T_max = 5.0      # maximum thrust magnitude

# Specific impulse and mass-flow-rate coefficient
Isp = 15.0
alpha_m = 1.0 / (Isp * g0)   # = 1/15

# Initial state
r0 = np.array([1.0, 4.0])
v0 = np.array([0.3, -2.0])
z0 = np.log(m_wet)
x0 = np.array([r0[0], r0[1], v0[0], v0[1], z0])

# Terminal conditions (position and velocity must reach these; mass is free)
rf = np.array([0.0, 0.0])
vf = np.array([0.0, 0.0])

# Glideslope constraint: ry >= tan(gamma_gs) * |rx|
# Keeps the rocket inside a cone above the landing site.
gamma_gs = np.pi / 4.0        # 45 degrees from vertical
tan_gs = np.tan(gamma_gs)     # = 1.0

# Fixed time of flight
tf = 4.0

# Number of control intervals (zero-order hold)
N = 50

# Time step
dt = tf / N

# Maximum allowable fuel consumption for verification:  m_wet - m_final < max_fuel
max_fuel = 0.85


def continuous_dynamics(x, u):
    """Evaluate dx/dt = f(x, u).

    Parameters
    ----------
    x : ndarray (5,)
        State [rx, ry, vx, vy, z] where z = ln(mass).
    u : ndarray (2,)
        Thrust force [Tx, Ty].

    Returns
    -------
    dxdt : ndarray (5,)
    """
    z = x[4]
    mass_inv = np.exp(-z)
    sigma = np.linalg.norm(u)

    return np.array([
        x[2],                           # drx/dt = vx
        x[3],                           # dry/dt = vy
        u[0] * mass_inv,                # dvx/dt = Tx / m
        u[1] * mass_inv - g0,           # dvy/dt = Ty / m - g
        -alpha_m * sigma * mass_inv     # dz/dt  = -alpha * ||T|| / m
    ])
