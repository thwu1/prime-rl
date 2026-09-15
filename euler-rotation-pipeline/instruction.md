`/app/` contains a biomechanical motion analysis environment with existing code in `/app/legacy/` and sample data in `/app/data/`.

Deliver two files:

**`/app/librotcore.so`** — C shared library (compiled with `-shared -fPIC -lm`) exporting with C linkage:

- `void rotcore_compose(const double angles[3], const char* seq, double R_out[9])` — row-major 3×3 rotation matrix from three angles and a rotation sequence string. Must support all 12 valid three-axis sequences: XYZ, XZY, YXZ, YZX, ZXY, ZYX, XYX, XZX, YXY, YZY, ZXZ, ZYZ.
- `int rotcore_decompose(const double R[9], const char* seq, double angles[3])` — extract angles (radians) for the given sequence. Return 0 normally, 1 at gimbal lock. Recomposing the returned angles must reproduce the input matrix within 1e-10.
- `void rotcore_mat_to_quat(const double R[9], double q[4])` — unit quaternion `[w,x,y,z]`, `w≥0`. Must be numerically stable across the full rotation range.

**`/app/rotations.py`** — Python CLI reading JSON from stdin, writing JSON to stdout. Must dynamically load `/app/librotcore.so` for all rotation matrix computations (must fail if the `.so` is absent).

Commands and JSON contracts:

`compose`: `{"command":"compose","angles":[a,b,g],"sequence":"SEQ"}` → `{"matrix":[[...],[...],[...]]}`.

`decompose`: `{"command":"decompose","matrix":[[...]],"sequence":"SEQ"}` → `{"angles":[a,b,g]}`. Recomposition must match the input matrix within 1e-10.

`continuous`: `{"command":"continuous","matrices":[...],"sequence":"SEQ"}` → `{"angle_series":[[a,b,g],...],"gimbal_lock_frames":[...]}`. Angle series must be continuous (max frame-to-frame change < 0.5 rad per component) and each frame's angles must recompose to its original matrix within 1e-6. Frames near singularity must be reported in `gimbal_lock_frames`.

`angular_velocity`: `{"command":"angular_velocity","matrices":[...],"dt":float}` → `{"omega":[[wx,wy,wz],...]}`. World-frame angular velocity vector per frame, one entry per input matrix.

`convert`: `{"command":"convert","from":"<repr>","to":"<repr>","value":<data>}` → `{"value":<result>}`. Representations: `matrix` (3×3 list), `quaternion` ([w,x,y,z], unit norm, w≥0), `helical` ([hx,hy,hz] where magnitude = rotation angle), `euler` ({"angles":[],"sequence":""}). When target is `euler`, `"sequence"` must appear in `value`. All round-trips within 1e-10.

`batch`: `{"command":"batch","trial_file":"<path>","conventions_file":"<path>","dt":float}` → `{"joints":{"<name>":{"sequence":"...","angles":[...],"angular_velocity":[...],"gimbal_lock_frames":[...]}}}`. Also writes `/app/results.db` (SQLite) with tables:
- `joint_angles(joint TEXT, frame INTEGER, a0 REAL, a1 REAL, a2 REAL, sequence TEXT, gimbal_locked INTEGER, PRIMARY KEY(joint, frame))`
- `angular_velocity(joint TEXT, frame INTEGER, wx REAL, wy REAL, wz REAL, PRIMARY KEY(joint, frame))`

Trial format: `{"sampling_rate":float,"frames":[{"frame":int,"joints":{"<name>":[[3×3]],...}},...]}`. Conventions: `{"<joint>":{"sequence":"...",...}}`. Process only joints present in both files. Re-running batch must not fail due to existing data.
