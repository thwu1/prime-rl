"""
FMI 2.0-style co-simulation subsystems for a PI-controlled DC electric drive.

Each subsystem exposes:
  - initialize(): reset internal state
  - doStep(t, dt, inputs) -> outputs: advance from t to t+dt with constant inputs
  - getState() -> dict: snapshot internal state for rollback
  - setState(state): restore a previously saved snapshot

The system models a DC permanent magnet motor driving a load through an ideal gear,
with a PI speed controller and external stimuli (speed reference + load torque).

"""

import math


class Subsystem:
    """Base class for FMI-like co-simulation subsystems."""

    def initialize(self):
        raise NotImplementedError

    def doStep(self, t, dt, inputs):
        raise NotImplementedError

    def getState(self):
        raise NotImplementedError

    def setState(self, state):
        raise NotImplementedError


class StimuliSubsystem(Subsystem):
    """Generates reference signals: desired angular velocity and load torque.

    Outputs (algebraic, no internal dynamics):
      - w_desired: step from 0 to 10 rad/s at t = 0.1 s
      - LoadTorque_Nm: step from 0 to 3 N*m at t = 0.5 s
    """

    def __init__(self):
        self.params = {
            'w_step_time': 0.1,
            'w_step_height': 10.0,
            'tau_step_time': 0.5,
            'tau_step_height': 3.0,
        }

    def initialize(self):
        pass

    def doStep(self, t, dt, inputs):
        p = self.params
        w_desired = p['w_step_height'] if t >= p['w_step_time'] else 0.0
        tau_ext = p['tau_step_height'] if t >= p['tau_step_time'] else 0.0
        return {'w_desired': w_desired, 'LoadTorque_Nm': tau_ext}

    def getState(self):
        return {}

    def setState(self, state):
        pass


class ControllerSubsystem(Subsystem):
    """PI speed controller.

    Inputs:
      - w_desired: reference angular velocity [rad/s]
      - w: measured angular velocity [rad/s]

    State:
      - x_i: integrator state (integral of speed error)

    Output:
      - V: armature voltage command [V]

    Transfer function: V(s) = k * (1 + 1/(T*s)) * e(s),  e = w_desired - w
    """

    def __init__(self):
        self.k = 0.1
        self.T = 0.005
        self.x_i = 0.0

    def initialize(self):
        self.x_i = 0.0

    def doStep(self, t, dt, inputs):
        w_desired = inputs['w_desired']
        w = inputs['w']

        e = w_desired - w
        # dx_i/dt = e (constant during step) => exact integration
        self.x_i += dt * e

        V = self.k * e + (self.k / self.T) * self.x_i
        return {'V': V}

    def getState(self):
        return {'x_i': self.x_i}

    def setState(self, state):
        self.x_i = state['x_i']


class DriveSubsystem(Subsystem):
    """DC permanent magnet motor with ideal gear and load inertia.

    Inputs:
      - V: armature voltage [V]
      - LoadTorque_Nm: external load torque on load side [N*m]

    States:
      - ia: armature current [A]
      - wl: load-side angular velocity [rad/s]

    Output:
      - w: load-side angular velocity [rad/s]

    Equations (referred to load side):
      La * dia/dt = V - Ra*ia - ke*ratio*wl
      Jl_eff * dwl/dt = kt*ia/ratio - tau_ext
      where Jl_eff = Jr*ratio^2 + J

    Parameters from Modelica Standard Library DcPermanentMagnetData defaults
    with Jr=0.001, wNominal=149.226, brushParameters.V=0.7.
    """

    MAX_INTERNAL_STEP = 0.001

    def __init__(self):
        self.Ra = 0.05
        self.La = 0.0015
        self.ke = 0.6273
        self.kt = 0.6273
        self.Jr = 0.001
        self.J = 1.0
        self.ratio = 10.0
        self.Jl_eff = self.Jr * self.ratio ** 2 + self.J
        self.ia = 0.0
        self.wl = 0.0

    def initialize(self):
        self.ia = 0.0
        self.wl = 0.0

    def _rhs(self, ia, wl, V, tau_ext):
        dia = (V - self.Ra * ia - self.ke * self.ratio * wl) / self.La
        dwl = (self.kt * ia / self.ratio - tau_ext) / self.Jl_eff
        return dia, dwl

    def doStep(self, t, dt, inputs):
        V = inputs['V']
        tau_ext = inputs['LoadTorque_Nm']

        n_sub = max(1, int(math.ceil(dt / self.MAX_INTERNAL_STEP)))
        h_sub = dt / n_sub

        for _ in range(n_sub):
            ia, wl = self.ia, self.wl
            # RK4 integration
            k1_ia, k1_wl = self._rhs(ia, wl, V, tau_ext)
            k2_ia, k2_wl = self._rhs(
                ia + h_sub / 2 * k1_ia, wl + h_sub / 2 * k1_wl, V, tau_ext)
            k3_ia, k3_wl = self._rhs(
                ia + h_sub / 2 * k2_ia, wl + h_sub / 2 * k2_wl, V, tau_ext)
            k4_ia, k4_wl = self._rhs(
                ia + h_sub * k3_ia, wl + h_sub * k3_wl, V, tau_ext)
            self.ia = ia + h_sub / 6 * (k1_ia + 2 * k2_ia + 2 * k3_ia + k4_ia)
            self.wl = wl + h_sub / 6 * (k1_wl + 2 * k2_wl + 2 * k3_wl + k4_wl)

        return {'w': self.wl}

    def getState(self):
        return {'ia': self.ia, 'wl': self.wl}

    def setState(self, state):
        self.ia = state['ia']
        self.wl = state['wl']
