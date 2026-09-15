# Pose Graph Data Specification

## Input Database: /app/pose_graph.db (SQLite3)

The pose graph is stored in a SQLite database with two tables.

### Table: nodes

| Column | Type    | Description                              |
|--------|---------|------------------------------------------|
| id     | INTEGER | Node identifier (0-indexed, primary key) |
| x      | REAL    | X position in meters (global frame)      |
| y      | REAL    | Y position in meters (global frame)      |
| theta  | REAL    | Heading in radians, range (-pi, pi]      |

These are initial pose estimates derived from dead-reckoning (noisy).

### Table: edges

| Column      | Type    | Description                                     |
|-------------|---------|-------------------------------------------------|
| id          | INTEGER | Auto-increment primary key                      |
| from_id     | INTEGER | Source node ID (FK -> nodes.id)                 |
| to_id       | INTEGER | Target node ID (FK -> nodes.id)                 |
| dx          | REAL    | Translation x in from_id's local frame (meters) |
| dy          | REAL    | Translation y in from_id's local frame (meters) |
| dtheta      | REAL    | Heading change (radians)                        |
| info_matrix | BLOB    | Information matrix — see format below            |
| edge_type   | TEXT    | `"odometry"` or `"loop_closure"`                |

### Information Matrix BLOB Format

The `info_matrix` column stores the upper triangle of a 3x3 symmetric positive-definite matrix as **6 packed little-endian IEEE 754 double-precision floats** (48 bytes total):

    bytes 0-47: [I_00, I_01, I_02, I_11, I_12, I_22]  (each 8 bytes, little-endian)

Reconstruct the full matrix as:

    | I_00  I_01  I_02 |
    | I_01  I_11  I_12 |
    | I_02  I_12  I_22 |

This is the **information matrix** (inverse of the measurement covariance) for the [x, y, theta] dimensions.

### SE(2) Measurement Convention

An edge measurement Z = (dx, dy, dtheta) encodes the relative transform:

    Z = X_i^{-1} * X_j

Concretely:
- `(dx, dy) = R(theta_i)^T * (p_j - p_i)`
- `dtheta = theta_j - theta_i` (normalized to (-pi, pi])

where `R(theta)` is the 2D rotation matrix.

## SE(2) C Library: /app/tools/

C source implementing SE(2) pose operations. Compile with `make` in `/app/tools/` to produce `libse2.so`.

**Header** (`se2_ops.h`):

```c
double se2_normalize_angle(double a);

void se2_compose(double ax, double ay, double at,
                 double bx, double by, double bt,
                 double *rx, double *ry, double *rt);

void se2_inverse(double ax, double ay, double at,
                 double *rx, double *ry, double *rt);

void se2_edge_error(double xi_x, double xi_y, double xi_t,
                    double xj_x, double xj_y, double xj_t,
                    double z_dx, double z_dy, double z_dt,
                    double *ex, double *ey, double *et);
```

All pointer parameters are outputs. The library must be loaded as a shared object to call from other languages.

## Output: /app/result.json

JSON array of optimized poses:

```json
[
  {"id": 0, "x": 0.0, "y": 0.0, "theta": 0.0},
  {"id": 1, "x": 5.01, "y": -0.03, "theta": 0.002},
  ...
]
```

All 20 nodes must be present, ordered by `id`.
