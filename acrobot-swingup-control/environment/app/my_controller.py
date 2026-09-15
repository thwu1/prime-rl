"""
Acrobot swing-up and stabilization controller.

Implement a controller that swings the acrobot from the stable hanging
position to the unstable inverted position and holds it there.

The acrobot is a double pendulum where only the second joint is actuated.

Available plant methods
-----------------------
plant.mass_matrix(x)        -> ndarray (2,2)
plant.coriolis_matrix(x)    -> ndarray (2,2)
plant.gravity_vector(x)     -> ndarray (2,)
plant.friction_vector(x)    -> ndarray (2,)
plant.forward_dynamics(x,u) -> ndarray (2,)   joint accelerations
plant.rhs(t, x, u)          -> ndarray (4,)   state derivative
plant.forward_kinematics(q) -> (ee_x, ee_y)   end-effector position
plant.kinetic_energy(x)     -> float
plant.potential_energy(x)   -> float
plant.total_energy(x)       -> float

Plant attributes: m1, m2, l1, l2, r1, r2, I1, I2, Ir, gr, g,
                  b1, b2, cf1, cf2, torque_limit, B
"""


class MyController:
    def __init__(self, plant):
        """
        Parameters
        ----------
        plant : DoublePendulumPlant
        """
        self.plant = plant

    def get_control_output(self, x, t):
        """
        Compute motor torques for the current state.

        Parameters
        ----------
        x : ndarray, shape=(4,)
            [q1, q2, qd1, qd2] in [rad, rad, rad/s, rad/s]
        t : float
            simulation time [s]

        Returns
        -------
        list or ndarray, shape=(2,)
            [u1, u2] in [Nm].  u1 is always clipped to 0 for the acrobot.
        """
        # --- Replace this with your controller implementation ---
        return [0.0, 0.0]
