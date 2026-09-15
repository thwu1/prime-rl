"""Reward computation system for quadruped locomotion.

Implements sigmoid-based tolerance functions and reward/cost components
for locomotion control tasks. Based on the dm_control reward utilities
and MuJoCo Playground's reward framework.
"""

import numpy as np

_DEFAULT_VALUE_AT_MARGIN = 0.1


def _sigmoids(x, value_at_1, sigmoid):
    """Map normalized distance to a decay value via a sigmoid curve.

    Args:
        x: Normalized distance from bounds (non-negative for well-formed inputs).
        value_at_1: The sigmoid output when x == 1.
        sigmoid: Name of the sigmoid type to use.

    Returns:
        Sigmoid value, typically in [0, 1] for non-negative x.
    """
    if sigmoid in ("cosine", "linear", "quadratic"):
        if not 0 <= value_at_1 < 1:
            raise ValueError(
                f"`value_at_1` must be in [0, 1), got {value_at_1}."
            )
    else:
        if not 0 < value_at_1 < 1:
            raise ValueError(
                f"`value_at_1` must be in (0, 1), got {value_at_1}."
            )

    if sigmoid == "gaussian":
        scale = np.sqrt(-2 * np.log(1.0 - value_at_1))
        return np.exp(-0.5 * (x * scale) ** 2)

    elif sigmoid == "hyperbolic":
        scale = np.arccosh(1 / value_at_1)
        return 1 / np.cosh(x * scale)

    elif sigmoid == "long_tail":
        scale = np.sqrt(1 / value_at_1 - 1)
        return 1 / ((x * scale) ** 2 + 1)

    elif sigmoid == "reciprocal":
        scale = 1 / value_at_1 - 1
        return 1 / (np.abs(x) * scale + 1)

    elif sigmoid == "cosine":
        scale = np.arccos(2 * value_at_1 - 1) / np.pi
        scaled_x = x * scale
        return np.where(
            np.abs(scaled_x) < 1,
            (1 + np.cos(np.pi * scaled_x)) / 2,
            0.0,
        )

    elif sigmoid == "linear":
        scale = 1 - value_at_1
        scaled_x = x * scale
        return np.where(np.abs(scaled_x) < 1, 1 - scaled_x, 0.0)

    elif sigmoid == "quadratic":
        scale = np.sqrt(1 - value_at_1)
        scaled_x = x * scale
        return np.where(np.abs(scaled_x) < 1, 1 - scaled_x ** 2, 0.0)

    elif sigmoid == "tanh_squared":
        scale = np.arctanh(np.sqrt(1 - value_at_1))
        return 1 - np.tanh(x * scale) ** 2

    else:
        raise ValueError(f"Unknown sigmoid type {sigmoid!r}.")


def tolerance(x, bounds=(0.0, 0.0), margin=0.0, sigmoid="gaussian",
              value_at_margin=_DEFAULT_VALUE_AT_MARGIN):
    """Returns 1 when x falls inside the bounds, between 0 and 1 otherwise.

    Args:
        x: Input value or array.
        bounds: Inclusive (lower, upper) bounds for the target interval.
        margin: Controls steepness of decay outside bounds. When 0, the
            output is binary (1 inside bounds, 0 outside).
        sigmoid: Sigmoid type for the smooth decay outside bounds.
        value_at_margin: Output value when distance from bounds equals margin.

    Returns:
        Value(s) between 0.0 and 1.0.

    Raises:
        ValueError: If bounds or margin are invalid.
    """
    lower, upper = bounds
    if lower > upper:
        raise ValueError("Lower bound must be <= upper bound.")
    if margin < 0:
        raise ValueError("`margin` must be non-negative.")

    in_bounds = np.logical_and(lower <= x, x <= upper)
    if margin == 0:
        return np.where(in_bounds, 1.0, 0.0)
    else:
        d = np.where(x < lower, lower - x, x - upper) / margin
        return np.where(in_bounds, 1.0, _sigmoids(d, value_at_margin, sigmoid))


class RewardComputer:
    """Computes individual reward/cost components for locomotion tasks.

    Implements the reward components used in quadruped locomotion training.
    Each method computes a single scalar reward or cost value from the
    current simulation state.

    Args:
        sigma: Bandwidth parameter for velocity tracking rewards.
        swing_height: Target maximum foot height during swing phase.
    """

    def __init__(self, sigma=0.25, swing_height=0.08):
        self.sigma = sigma
        self.swing_height = swing_height

    def tracking_lin_vel(self, commands, local_vel):
        """Reward for tracking commanded linear velocity (xy plane).

        Computes an exponentially-shaped reward based on the velocity
        tracking error in the local frame's xy plane.
        """
        lin_vel_error = np.sum(np.abs(commands[:2] - local_vel[:2]))
        return np.exp(-lin_vel_error / self.sigma)

    def tracking_ang_vel(self, commands, ang_vel):
        """Reward for tracking commanded yaw rate."""
        ang_vel_error = (commands[2] - ang_vel[2]) ** 2
        return np.exp(-ang_vel_error / self.sigma)

    def cost_lin_vel_z(self, global_linvel):
        """Penalize vertical base linear velocity."""
        return global_linvel[2] ** 2

    def cost_ang_vel_xy(self, global_angvel):
        """Penalize roll and pitch angular velocity."""
        return np.sum(global_angvel ** 2)

    def cost_orientation(self, up_vector):
        """Penalize non-upright base orientation.

        The up_vector is the z-axis of the torso frame expressed in
        world coordinates. For an upright robot, up_vector ≈ [0, 0, 1],
        so the xy components should be near zero.
        """
        return np.sum(up_vector[:2] ** 2)

    def cost_action_rate(self, action, prev_action):
        """Penalize rapid changes in control actions."""
        return np.sum((action - prev_action) ** 2)

    def cost_torques(self, actuator_force):
        """Combined L2/L1 torque penalty.

        Uses both the L2 norm (for smoothness) and L1 norm (for sparsity)
        of the actuator forces.
        """
        return np.sqrt(np.sum(actuator_force ** 2)) + np.sum(np.abs(actuator_force))

    def cost_joint_limits(self, joint_pos, soft_lowers, soft_uppers):
        """Penalize joints exceeding soft position limits.

        Uses the tolerance function with a Gaussian sigmoid to create
        smooth penalties as joints approach and exceed their soft limits.
        """
        violations = 0.0
        for i in range(len(joint_pos)):
            tol_val = tolerance(
                joint_pos[i],
                bounds=(soft_lowers[i], soft_uppers[i]),
                margin=0.1,
                sigmoid="gaussian",
                value_at_margin=0.1,
            )
            violations += 1.0 - tol_val
        return violations

    def reward_feet_air_time(self, air_time, first_contact, cmd_norm):
        """Reward appropriate feet air time during locomotion.

        Encourages a minimum air time of 0.1 seconds per swing phase.
        Only active when the robot is commanded to move.
        """
        rew = np.sum((air_time - 0.1) * first_contact)
        return rew * float(cmd_norm > 0.01)

    def cost_feet_clearance(self, foot_z, foot_vel, gait_phase):
        """Penalize feet not tracking gait-defined clearance trajectory.

        Computes the deviation between actual foot height and the reference
        height from the cubic Bézier gait trajectory, weighted by foot
        lateral velocity magnitude.
        """
        from gait_utils import get_rz
        target_z = np.array([
            get_rz(gait_phase[f], self.swing_height)
            for f in range(len(gait_phase))
        ])
        vel_xy = foot_vel[..., :2]
        vel_norm = np.sqrt(np.linalg.norm(vel_xy, axis=-1))
        delta = np.abs(foot_z - target_z)
        return np.sum(delta * vel_norm)

    def compute_all(self, commands, local_vel, ang_vel, global_linvel,
                    global_angvel, up_vector, actions, prev_actions,
                    actuator_force, joint_pos, soft_lowers, soft_uppers,
                    air_time, first_contact, foot_z, foot_vel, gait_phase):
        """Compute all reward components for a single timestep.

        Returns:
            Dictionary mapping component names to scalar values.
        """
        cmd_norm = np.linalg.norm(commands)
        return {
            'tracking_lin_vel': self.tracking_lin_vel(commands, local_vel),
            'tracking_ang_vel': self.tracking_ang_vel(commands, ang_vel),
            'lin_vel_z': self.cost_lin_vel_z(global_linvel),
            'ang_vel_xy': self.cost_ang_vel_xy(global_angvel),
            'orientation': self.cost_orientation(up_vector),
            'action_rate': self.cost_action_rate(actions, prev_actions),
            'torques': self.cost_torques(actuator_force),
            'joint_limits': self.cost_joint_limits(joint_pos, soft_lowers, soft_uppers),
            'feet_air_time': self.reward_feet_air_time(air_time, first_contact, cmd_norm),
            'feet_clearance': self.cost_feet_clearance(foot_z, foot_vel, gait_phase),
        }
