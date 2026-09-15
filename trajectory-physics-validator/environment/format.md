# Trajectory Data Format (HDF5)

Each `.h5` file describes a rigid-body physics simulation trajectory.

## File structure

```
/ (root group)
  Attributes:
    dt       float     Time step between consecutive frames (seconds)
    floor_z  float     Z-coordinate of the ground plane (metres)

  Datasets:
    gravity  (3,)      Gravitational acceleration vector [gx, gy, gz] (m/s²)

  Groups (one per body, keyed by body name):
    /<body_name>/
      Attributes:
        mass        float     Mass (kg)
        shape_type  string    "sphere" or "ellipsoid"

      Datasets:
        shape_params       (P,)      Shape parameters:
                                       sphere: [radius]
                                       ellipsoid: [a, b, c] semi-axis lengths
        inertia_tensor     (3, 3)    Inertia tensor in body principal-axis frame (kg·m²)
        positions          (N, 3)    Centre-of-mass positions [x, y, z] (m)
        quaternions        (N, 4)    Orientation quaternions [w, x, y, z] (scalar-first)
        velocities         (N, 3)    Linear velocities [vx, vy, vz] (m/s)
        angular_velocities (N, 3)    Angular velocities [ωx, ωy, ωz] (rad/s) in world frame
```

## Conventions

- SI units throughout.
- Positive Z is up.
- Quaternions use scalar-first convention: q = [w, x, y, z].
- The quaternion represents the rotation from body frame to world frame.
- Inertia tensors are given in the body's principal-axis frame (diagonal for principal axes). For world-frame calculations, they must be rotated by the orientation quaternion.
- Angular velocities are expressed in the world frame.
- The ground plane (if present) is at `z = floor_z`; a sphere rests on it when its centre is at `z = floor_z + radius`.
