"""
Rigid body state representation and dynamics for the spatial double pendulum.

"""

import numpy as np


def quat_to_rotation(q):
    """Convert a unit quaternion [w, x, y, z] to a 3x3 rotation matrix."""
    w, x, y, z = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - w*z),     2*(x*z + w*y)],
        [2*(x*y + w*z),     1 - 2*(x*x + z*z), 2*(y*z - w*x)],
        [2*(x*z - w*y),     2*(y*z + w*x),     1 - 2*(x*x + y*y)]
    ])


def quat_G(q):
    """
    Compute the G matrix relating angular velocity omega (body frame)
    to quaternion derivative: dq/dt = 0.5 * E(q) * omega
    where E is the 4x3 matrix.

    For q = [w, x, y, z]:
    E = [[-x, -y, -z],
         [ w, -z,  y],
         [ z,  w, -x],
         [-y,  x,  w]]

    G = 0.5 * E
    """
    w, x, y, z = q
    return 0.5 * np.array([
        [-x, -y, -z],
        [ w, -z,  y],
        [ z,  w, -x],
        [-y,  x,  w]
    ])


def skew(v):
    """Skew-symmetric matrix from a 3-vector."""
    return np.array([
        [0,    -v[2],  v[1]],
        [v[2],  0,    -v[0]],
        [-v[1], v[0],  0]
    ])


class RigidBody:
    """
    State of a single rigid body in 3D.

    Generalized coordinates: q = [x, y, z, e0, e1, e2, e3]  (7 DOF)
        - (x, y, z): position of center of mass
        - (e0, e1, e2, e3): Euler parameters (quaternion) [w, x, y, z]

    Generalized velocities: v = [vx, vy, vz, wx, wy, wz]  (6 DOF)
        - (vx, vy, vz): translational velocity of CM
        - (wx, wy, wz): angular velocity in body frame

    Generalized accelerations: a = [ax, ay, az, alpha_x, alpha_y, alpha_z]  (6 DOF)
    """

    def __init__(self, mass, inertia, length):
        self.mass = mass
        self.inertia = inertia.copy()  # 3x3 inertia tensor in body frame
        self.length = length

        # State vectors
        self.pos = np.zeros(3)         # CM position
        self.quat = np.array([1.0, 0.0, 0.0, 0.0])  # quaternion [w,x,y,z]
        self.vel = np.zeros(3)         # CM velocity
        self.omega = np.zeros(3)       # angular velocity (body frame)
        self.acc = np.zeros(3)         # CM acceleration
        self.alpha = np.zeros(3)       # angular acceleration (body frame)

    def get_rotation_matrix(self):
        """Return the body's rotation matrix."""
        return quat_to_rotation(self.quat)

    def get_point_global(self, local_point):
        """Transform a body-local point to global coordinates."""
        R = self.get_rotation_matrix()
        return self.pos + R @ local_point

    def get_mass_matrix(self):
        """
        Return the 6x6 generalized mass matrix [M 0; 0 J] in
        the velocity coordinates (v, omega).
        """
        M = np.zeros((6, 6))
        M[0:3, 0:3] = self.mass * np.eye(3)
        M[3:6, 3:6] = self.inertia
        return M

    def get_generalized_force(self, gravity):
        """
        Return the 6-vector of generalized forces (gravity + gyroscopic).
        f = [m*g; -omega x (J*omega)]
        """
        f = np.zeros(6)
        f[0:3] = self.mass * gravity
        f[3:6] = -np.cross(self.omega, self.inertia @ self.omega)
        return f

    def get_coords(self):
        """Return the 7-vector of generalized coordinates [pos; quat]."""
        return np.concatenate([self.pos, self.quat])

    def get_velocities(self):
        """Return the 6-vector of generalized velocities [vel; omega]."""
        return np.concatenate([self.vel, self.omega])

    def get_accelerations(self):
        """Return the 6-vector of generalized accelerations [acc; alpha]."""
        return np.concatenate([self.acc, self.alpha])

    def set_coords(self, q):
        """Set generalized coordinates from a 7-vector."""
        self.pos = q[0:3].copy()
        self.quat = q[3:7].copy()

    def set_velocities(self, v):
        """Set generalized velocities from a 6-vector."""
        self.vel = v[0:3].copy()
        self.omega = v[3:6].copy()

    def set_accelerations(self, a):
        """Set generalized accelerations from a 6-vector."""
        self.acc = a[0:3].copy()
        self.alpha = a[3:6].copy()


class DoublePendulumSystem:
    """
    Spatial double pendulum system with two rigid links.

    Link 1 is attached to a fixed pivot at the origin via a spherical joint
    at its top end (local point [0, 0, +L1/2]).

    Link 2 is attached to link 1 at link 1's bottom end (local point [0, 0, -L1/2])
    via a spherical joint at link 2's top end (local point [0, 0, +L2/2]).

    Constraints (6 total):
      - 3 for spherical joint 1: link1 top = pivot
      - 3 for spherical joint 2: link1 bottom = link2 top
    Quaternion unit-norm is enforced by algebraic renormalization, not as a DAE constraint.
    """

    def __init__(self, config):
        self.config = config

        # Create the two links
        self.link1 = RigidBody(
            mass=config.LINK1_MASS,
            inertia=config.LINK1_INERTIA,
            length=config.LINK1_LENGTH
        )
        self.link2 = RigidBody(
            mass=config.LINK2_MASS,
            inertia=config.LINK2_INERTIA,
            length=config.LINK2_LENGTH
        )

        self.bodies = [self.link1, self.link2]
        self.pivot = config.PIVOT_POINT.copy()

        # Local attachment points on each body
        self.link1_top_local = np.array([0.0, 0.0, self.link1.length / 2.0])
        self.link1_bot_local = np.array([0.0, 0.0, -self.link1.length / 2.0])
        self.link2_top_local = np.array([0.0, 0.0, self.link2.length / 2.0])

        # Number of generalized coords, velocities, constraints
        self.n_coords = 14       # 7 per body
        self.n_vel = 12          # 6 per body
        # 6 constraints: 3 per spherical joint
        self.n_constraints = 6

    def set_initial_conditions(self):
        """
        Set initial conditions: link 1 hangs at 30 degrees from vertical
        in the x-z plane, link 2 at 45 degrees from vertical.
        Both start from rest.
        """
        theta1 = np.radians(30)
        theta2 = np.radians(45)

        # Link 1: rotated theta1 about y-axis
        q1 = np.array([np.cos(theta1/2), 0, np.sin(theta1/2), 0])
        R1 = quat_to_rotation(q1)
        # CM of link 1 is at pivot + R1 * [0, 0, -L1/2]
        pos1 = self.pivot + R1 @ np.array([0, 0, -self.link1.length/2])

        self.link1.pos = pos1
        self.link1.quat = q1
        self.link1.vel = np.zeros(3)
        self.link1.omega = np.zeros(3)
        self.link1.acc = np.zeros(3)
        self.link1.alpha = np.zeros(3)

        # Bottom of link 1
        link1_bot = self.link1.get_point_global(self.link1_bot_local)

        # Link 2: rotated theta2 about y-axis
        q2 = np.array([np.cos(theta2/2), 0, np.sin(theta2/2), 0])
        R2 = quat_to_rotation(q2)
        pos2 = link1_bot + R2 @ np.array([0, 0, -self.link2.length/2])

        self.link2.pos = pos2
        self.link2.quat = q2
        self.link2.vel = np.zeros(3)
        self.link2.omega = np.zeros(3)
        self.link2.acc = np.zeros(3)
        self.link2.alpha = np.zeros(3)

    def get_all_coords(self):
        """Return full coordinate vector (14)."""
        return np.concatenate([b.get_coords() for b in self.bodies])

    def get_all_velocities(self):
        """Return full velocity vector (12)."""
        return np.concatenate([b.get_velocities() for b in self.bodies])

    def get_all_accelerations(self):
        """Return full acceleration vector (12)."""
        return np.concatenate([b.get_accelerations() for b in self.bodies])

    def set_all_coords(self, q):
        """Set coordinates for all bodies from a 14-vector."""
        self.link1.set_coords(q[0:7])
        self.link2.set_coords(q[7:14])

    def set_all_velocities(self, v):
        """Set velocities for all bodies from a 12-vector."""
        self.link1.set_velocities(v[0:6])
        self.link2.set_velocities(v[6:12])

    def set_all_accelerations(self, a):
        """Set accelerations for all bodies from a 12-vector."""
        self.link1.set_accelerations(a[0:6])
        self.link2.set_accelerations(a[6:12])

    def get_mass_matrix(self):
        """Return the block-diagonal 12x12 mass matrix."""
        M = np.zeros((self.n_vel, self.n_vel))
        M[0:6, 0:6] = self.link1.get_mass_matrix()
        M[6:12, 6:12] = self.link2.get_mass_matrix()
        return M

    def get_force_vector(self):
        """Return the 12-vector of generalized forces."""
        gravity = self.config.GRAVITY
        f = np.zeros(self.n_vel)
        f[0:6] = self.link1.get_generalized_force(gravity)
        f[6:12] = self.link2.get_generalized_force(gravity)
        return f

    def compute_kinetic_energy(self):
        """Compute total kinetic energy."""
        KE = 0.0
        for body in self.bodies:
            KE += 0.5 * body.mass * np.dot(body.vel, body.vel)
            KE += 0.5 * body.omega @ body.inertia @ body.omega
        return KE

    def compute_potential_energy(self):
        """Compute total gravitational potential energy."""
        PE = 0.0
        g_mag = abs(self.config.GRAVITY[2])
        for body in self.bodies:
            PE += body.mass * g_mag * body.pos[2]
        return PE

    def compute_total_energy(self):
        """Compute total mechanical energy."""
        return self.compute_kinetic_energy() + self.compute_potential_energy()

    def get_L_matrix(self):
        """
        Return the block-diagonal 14x12 velocity transformation matrix L
        such that dq/dt = L * v, where q is generalized coordinates (14)
        and v is generalized velocities (12).

        For each body: dq/dt = [vel; 0.5 * E(quat) * omega]
        so L_body = [[I_3, 0], [0, G(quat)]] where G is the 4x3 quat_G matrix.
        """
        L = np.zeros((self.n_coords, self.n_vel))

        # Body 1
        L[0:3, 0:3] = np.eye(3)
        L[3:7, 3:6] = quat_G(self.link1.quat)

        # Body 2
        L[7:10, 6:9] = np.eye(3)
        L[10:14, 9:12] = quat_G(self.link2.quat)

        return L
