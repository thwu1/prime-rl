#!/usr/bin/env python3
"""
Patches all bugs in the 2D shallow water flood solver project.

Build fixes (CMakeLists.txt):
  1. C++ standard 11 -> 17 (code uses std::optional from C++17)
  2. boundary.cpp missing from executable sources

Numerical fixes (solver.cpp):
  3. Manning's n must be squared in friction term
  4. hflow exponent must be 10/3, not 7/3
  5. CFL timestep formula: sqrt(g*max_h) not sqrt(g)*max_h
  6. Q=0 stability clamp must be replaced with semi-implicit fallback
     (Bates 2010: Q=(q0-g*dt*hflow*Sf)/denom*dx when Q opposes dh)
  7. Y-flux signs reversed in update_water_depths

Boundary fix (boundary.cpp):
  8. Reflective wall BC (flux negation) must be replaced with
     free-outflow BC (copy positive interior flux to boundary)

Simulation loop fix (main.cpp):
  9. enforce_outflow_boundary must be called AFTER compute_fluxes
     and BEFORE mass tracking / update_water_depths, not after
     update_water_depths where it currently sits
"""



def fix_cmake(path):
    with open(path) as f:
        code = f.read()

    # Fix 1: C++ standard 11 -> 17
    code = code.replace(
        "set(CMAKE_CXX_STANDARD 11)",
        "set(CMAKE_CXX_STANDARD 17)"
    )

    # Fix 2: Add boundary.cpp to sources
    code = code.replace(
        "    src/solver.cpp\n)",
        "    src/solver.cpp\n    src/boundary.cpp\n)"
    )

    with open(path, "w") as f:
        f.write(code)
    print(f"Fixed CMakeLists.txt: {path}")


def fix_solver(path):
    with open(path) as f:
        code = f.read()

    # Fix 3: Manning's n must be squared (fn -> fn*fn)
    code = code.replace(
        "hflow * fn * fabs(q0)",
        "hflow * fn * fn * fabs(q0)"
    )

    # Fix 4: hflow exponent 7/3 -> 10/3
    code = code.replace(
        "pow(hflow, 7.0 / 3.0)",
        "pow(hflow, 10.0 / 3.0)"
    )

    # Fix 5: CFL formula: sqrt(g)*max_h -> sqrt(g*max_h)
    code = code.replace(
        "cfg.cfl * grid.dx / (sqrt(cfg.g) * max_h)",
        "cfg.cfl * grid.dx / sqrt(cfg.g * max_h)"
    )

    # Fix 6: Replace Q=0 stability clamp with semi-implicit fallback
    # The Q=0 clamping prevents flow entirely; the correct Bates 2010
    # formulation falls back to the simplified semi-implicit scheme.
    code = code.replace(
        "    // Stability correction: zero out flux opposing head gradient\n"
        "    if (Q * dh < 0.0) {\n"
        "        Q = 0.0;\n"
        "    }",
        "    // Semi-implicit fallback: correct when Q and dh have opposite signs\n"
        "    if (Q * dh < 0.0) {\n"
        "        Q = (q0 - g * dt * hflow * Sf) / denom * grid.dx;\n"
        "    }"
    )

    # Fix 7: Y-flux signs in update_water_depths
    code = code.replace(
        "grid.Qy[qy_idx(j + 1, i, nc)] - grid.Qy[qy_idx(j, i, nc)]",
        "grid.Qy[qy_idx(j, i, nc)] - grid.Qy[qy_idx(j + 1, i, nc)]"
    )

    with open(path, "w") as f:
        f.write(code)
    print(f"Fixed solver.cpp: {path}")


def fix_boundary(path):
    with open(path) as f:
        code = f.read()

    # Fix 8: Replace reflective wall BC with free-outflow BC.
    # The reflective BC negates the interior flux, bouncing water back.
    # Free outflow copies the interior flux (when positive/southward)
    # to the boundary interface, allowing water to exit the domain.
    code = code.replace(
        "        // Mirror the interior flux to impose the boundary condition\n"
        "        double q_interior = grid.Qy[qy_idx(nr - 1, i, nc)];\n"
        "        grid.Qy[qy_idx(nr, i, nc)] = -q_interior;",
        "        double q = grid.Qy[qy_idx(nr - 1, i, nc)];\n"
        "        if (q > 0.0) {\n"
        "            grid.Qy[qy_idx(nr, i, nc)] = q;\n"
        "        } else {\n"
        "            grid.Qy[qy_idx(nr, i, nc)] = 0.0;\n"
        "        }"
    )

    with open(path, "w") as f:
        f.write(code)
    print(f"Fixed boundary.cpp: {path}")


def fix_main(path):
    with open(path) as f:
        code = f.read()

    # Fix 9: Move enforce_outflow_boundary from after update_water_depths
    # to after compute_fluxes. The boundary flux must be set BEFORE the
    # depth update so the continuity equation includes outflow at the
    # south boundary, and BEFORE mass tracking so outflow is recorded.

    # Remove from current (wrong) position after update_water_depths
    code = code.replace(
        "        // Update water depths (continuity)\n"
        "        update_water_depths(grid, cfg, dt);\n"
        "\n"
        "        // Outflow boundary (south edge)\n"
        "        enforce_outflow_boundary(grid);\n"
        "\n"
        "        // Advance old fluxes",
        "        // Update water depths (continuity)\n"
        "        update_water_depths(grid, cfg, dt);\n"
        "\n"
        "        // Advance old fluxes"
    )

    # Insert at correct position after compute_fluxes, before mass tracking
    code = code.replace(
        "        // Compute inter-cell fluxes\n"
        "        compute_fluxes(grid, cfg, dt);\n"
        "\n"
        "        // Track outflow at south boundary",
        "        // Compute inter-cell fluxes\n"
        "        compute_fluxes(grid, cfg, dt);\n"
        "\n"
        "        // Outflow boundary (south edge)\n"
        "        enforce_outflow_boundary(grid);\n"
        "\n"
        "        // Track outflow at south boundary"
    )

    with open(path, "w") as f:
        f.write(code)
    print(f"Fixed main.cpp: {path}")


if __name__ == "__main__":
    fix_cmake("/app/CMakeLists.txt")
    fix_solver("/app/src/solver.cpp")
    fix_boundary("/app/src/boundary.cpp")
    fix_main("/app/src/main.cpp")
