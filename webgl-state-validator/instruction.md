Design and implement a complete WebGL 1.0 state validation engine at `/app/validator.py` and bring the surrounding conformance pipeline to specification compliance.

The `WebGLStateValidator` class has three unimplemented methods covering texture completeness (TEXTURE_2D and TEXTURE_CUBE_MAP), framebuffer completeness, and draw-call precondition validation. Implement these from the specification reference at `/app/spec_reference.md`, which is authoritative for all validation semantics including default object state.

The pipeline's supporting subsystems — GLSL shader analysis (`/app/shader_analyzer.py`), shader-state cross-validation (`/app/conformance_check.py` with SQLite database at `/app/conformance.db`), and GL state definitions (`/app/state_types.py`) — contain integration defects that must be discovered through runtime investigation. The defects are not documented; diagnosis requires empirical testing of tool behavior, database schema inspection, and specification cross-referencing.

Supporting files: `/app/gl_constants.py`, `/app/shaders/`.

All conformance tests must pass.