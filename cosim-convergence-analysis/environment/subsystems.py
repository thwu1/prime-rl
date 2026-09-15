"""
Subsystem definitions for the controlled DC motor co-simulation.

System: PI-controlled DC permanent magnet motor with ideal gear and load inertia.

Decomposition into three subsystems:
  1. Stimuli: Generates reference speed and load torque signals (no dynamics)
  2. Controller: PI speed controller (1 state: integrator)
  3. Drive: DC PM motor + ideal gear + load inertia (2 states: armature current, load speed)

Coupling topology:
  Stimuli ---(w_desired)---> Controller ---(V)---> Drive
  Stimuli ---(tau_load)----> Drive
  Drive -------(w)---------> Controller (feedback)

All subsystems use plain Python (no external dependencies required).
"""


# System parameters
PARAMS = {
    "Ra": 0.05,                          # Armature resistance [Ohm]
    "La": 0.0015,                        # Armature inductance [H]
    "ke": 95.0 / 149.22565104552,        # Back-EMF constant [V*s/rad]
    "ratio": 10.0,                       # Gear ratio (motor-side / load-side)
    "J": 1.0,                            # Load inertia [kg*m^2]
    "Jr": 0.001,                         # Rotor inertia [kg*m^2]
    "k_PI": 0.1,                         # PI controller proportional gain
    "T_PI": 0.005,                       # PI controller integral time constant [s]
    "t_end": 1.0,                        # Simulation end time [s]
}
PARAMS["J_eff"] = PARAMS["J"] + PARAMS["Jr"] * PARAMS["ratio"] ** 2  # = 1.1


class Stimuli:
    """
    Subsystem 1: Signal generator (stateless).

    Outputs:
      w_desired(t): desired motor-side speed [rad/s] -- step from 0 to 10 at t = 0.1 s
      tau_load(t):  external load torque on the load inertia [N*m] -- step from 0 to 3 at t = 0.5 s
    """

    def outputs(self, t):
        w_desired = 10.0 if t >= 0.1 else 0.0
        tau_load = 3.0 if t >= 0.5 else 0.0
        return w_desired, tau_load


class Controller:
    """
    Subsystem 2: PI speed controller.

    State:
      x_i  --  integrator accumulator (scalar)

    Inputs (held constant during each macro step):
      w_desired  --  from Stimuli
      w          --  from Drive (feedback)

    Dynamics (linear, exact solution available):
      e       = w_desired - w
      dx_i/dt = e
      =>  x_i(t+H) = x_i(t) + H * e    (exact for constant held inputs)

    Output:
      V = k_PI * (e + x_i / T_PI)
    """

    def __init__(self):
        self.x_i = 0.0

    def integrate(self, H, w_desired, w):
        """Advance integrator by one macro step with held inputs (exact)."""
        e = w_desired - w
        self.x_i += H * e

    def output(self, w_desired, w):
        """Compute voltage command from current state and held inputs."""
        e = w_desired - w
        return PARAMS["k_PI"] * (e + self.x_i / PARAMS["T_PI"])


class Drive:
    """
    Subsystem 3: DC PM motor + ideal gear + load inertia.

    States:
      i_a     --  armature current [A]
      w_load  --  load-side angular velocity [rad/s]

    Inputs (held constant during each macro step):
      V         --  armature voltage from Controller [V]
      tau_load  --  external torque from Stimuli [N*m], applied on load side

    Dynamics:
      La    * di_a/dt    = V  -  Ra * i_a  -  ke * ratio * w_load
      J_eff * dw_load/dt = ke * ratio * i_a  +  tau_load

      where  J_eff = J + Jr * ratio^2  (effective inertia reflected to load side)

    Output:
      w = ratio * w_load   (motor-side angular velocity)
    """

    def __init__(self):
        self.i_a = 0.0
        self.w_load = 0.0

    def rhs(self, i_a, w_load, V, tau_load):
        """Return (di_a/dt, dw_load/dt)."""
        Ra = PARAMS["Ra"]
        La = PARAMS["La"]
        ke = PARAMS["ke"]
        ratio = PARAMS["ratio"]
        J_eff = PARAMS["J_eff"]
        di_a = (V - Ra * i_a - ke * ratio * w_load) / La
        dw_load = (ke * ratio * i_a + tau_load) / J_eff
        return di_a, dw_load

    def output(self):
        """Return motor-side speed w = ratio * w_load."""
        return PARAMS["ratio"] * self.w_load
