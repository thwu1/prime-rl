#!/usr/bin/env python3
"""
Previous attempt at stabilizing the pendulum system.
Uses proportional feedback on joint angles only.
"""
import mujoco
import numpy as np

model = mujoco.MjModel.from_xml_path('/app/model.xml')
data = mujoco.MjData(model)

# Proportional gains: cart position, angle1, angle2
Kp = np.array([10.0, 50.0, 50.0])

mujoco.mj_resetData(model, data)
data.qpos[:] = [0.0, 0.15, -0.1]

dt = model.opt.timestep
T = 10.0
steps = int(T / dt)

for i in range(steps):
    # Proportional feedback on positions only
    u = -Kp @ data.qpos
    data.ctrl[0] = np.clip(u, -100.0, 100.0)
    mujoco.mj_step(model, data)

    if i % 1000 == 0:
        print(f"t={data.time:.2f}  cart={data.qpos[0]:.3f}  "
              f"a1={data.qpos[1]:.3f}  a2={data.qpos[2]:.3f}")

print(f"\nFinal state at t={data.time:.2f}s:")
print(f"  angles: {data.qpos[1]:.4f}, {data.qpos[2]:.4f} rad")
print(f"  cart:   {data.qpos[0]:.4f} m")

if abs(data.qpos[1]) > 0.05 or abs(data.qpos[2]) > 0.05:
    print("STATUS: FAILED — pendulums not stabilized")
else:
    print("STATUS: OK")
