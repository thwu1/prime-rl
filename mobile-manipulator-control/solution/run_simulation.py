#!/usr/bin/env python3
"""Run closed-loop simulation and write error data CSV."""

import numpy as np
import yaml
import sys

sys.path.insert(0, '/app')
from youbot_controller import (
    next_state,
    compute_end_effector_config,
    feedback_control,
    compute_controls,
)

with open('/app/task_spec.yaml') as f:
    spec = yaml.safe_load(f)

chassis = spec['initial_config']['chassis']
config = np.array(
    [chassis['phi'], chassis['x'], chassis['y']]
    + spec['initial_config']['arm_joints']
    + spec['initial_config']['wheel_angles'],
    dtype=float,
)

R = np.array(spec['target_ee_pose']['rotation'], dtype=float)
p = np.array(spec['target_ee_pose']['translation'], dtype=float)
Xd = np.eye(4)
Xd[:3, :3] = R
Xd[:3, 3] = p
Xd_next = Xd.copy()

Kp = spec['controller']['Kp_scale'] * np.eye(6)
Ki = spec['controller']['Ki_scale'] * np.eye(6)
dt = spec['simulation']['timestep']
num_steps = spec['simulation']['num_steps']
speed_limit = spec['simulation']['speed_limit']

error_integral = np.zeros(6)

with open('/app/error_data.csv', 'w') as f:
    f.write('step,wx,wy,wz,vx,vy,vz\n')
    for step in range(num_steps):
        X = compute_end_effector_config(config)
        V, Xerr, error_integral = feedback_control(
            X, Xd, Xd_next, Kp, Ki, error_integral, dt,
        )
        ctrl = compute_controls(V, config)
        config = next_state(config, ctrl, dt, speed_limit)
        f.write(f'{step},{Xerr[0]:.6f},{Xerr[1]:.6f},{Xerr[2]:.6f},'
                f'{Xerr[3]:.6f},{Xerr[4]:.6f},{Xerr[5]:.6f}\n')

print('Wrote /app/error_data.csv')
