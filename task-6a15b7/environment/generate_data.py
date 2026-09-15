#!/usr/bin/env python3
"""Generate OpenFOAM-style case directories with simulation data.

This script runs during Docker build and is then deleted.
It creates realistic porous-media flow data in OpenFOAM directory structure.
"""
import json
import math
import os

# ---- Ground truth parameters (NOT exposed to the agent) ----
K_TRUE = 1.85e-10       # intrinsic permeability [m^2]
P_CONV = 2.12           # grid convergence order
BETA = 1.2e5            # Forchheimer coefficient [m^-1]

# ---- Physical parameters ----
MU = 1.0e-3             # dynamic viscosity [Pa.s]
RHO = 1000.0            # density [kg/m^3]
NU = MU / RHO           # kinematic viscosity [m^2/s]
L = 4.0e-3              # domain length [m]
H = 2.0e-3              # domain height [m]
POROSITY = 0.5567
D_P = 2.0e-4            # particle diameter [m]

# ---- Study configuration ----
MESH_DP = 0.50          # pressure drop for mesh study [Pa]
MESHES = [(100, 50), (200, 100), (400, 200)]
PRESSURES = [0.50, 1.00, 2.50, 5.00, 15.00, 50.00, 150.00, 500.00]

# Mesh error model: k_apparent(h) = K_TRUE + C * h^P_CONV
h_coarse = L / MESHES[0][0]
C_MESH = 0.05 * K_TRUE / (h_coarse ** P_CONV)

# Transient convergence parameters
TAU = 50.0
TIMES = [10.0, 25.0, 50.0, 100.0, 200.0, 500.0, 1000.0]


def forchheimer_velocity(dp_val, k):
    """Solve Forchheimer equation for steady-state superficial velocity."""
    grad_p = dp_val / L
    a_coeff = BETA * RHO
    b_coeff = MU / k
    discriminant = b_coeff * b_coeff + 4.0 * a_coeff * grad_p
    return 2.0 * grad_p / (b_coeff + math.sqrt(discriminant))


def write_transport_properties(dirpath):
    """Write OpenFOAM transportProperties file."""
    fpath = os.path.join(dirpath, "constant", "transportProperties")
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w") as f:
        f.write("FoamFile\n")
        f.write("{\n")
        f.write("    version     2.0;\n")
        f.write("    format      ascii;\n")
        f.write("    class       dictionary;\n")
        f.write("    location    \"constant\";\n")
        f.write("    object      transportProperties;\n")
        f.write("}\n")
        f.write("// * * * * * * * * * * * * * * * * * * * * * * //\n\n")
        f.write("transportModel  Newtonian;\n\n")
        f.write("nu              [0 2 -1 0 0 0 0] {:.6e};\n\n".format(NU))
        f.write("// Reference density for post-processing\n")
        f.write("rho             [1 -3 0 0 0 0 0] {:.1f};\n\n".format(RHO))
        f.write("// * * * * * * * * * * * * * * * * * * * * * * //\n")


def write_control_dict(dirpath, dp_val):
    """Write OpenFOAM controlDict file."""
    fpath = os.path.join(dirpath, "system", "controlDict")
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w") as f:
        f.write("FoamFile\n")
        f.write("{\n")
        f.write("    version     2.0;\n")
        f.write("    format      ascii;\n")
        f.write("    class       dictionary;\n")
        f.write("    location    \"system\";\n")
        f.write("    object      controlDict;\n")
        f.write("}\n")
        f.write("// * * * * * * * * * * * * * * * * * * * * * * //\n\n")
        f.write("application     simpleFoam;\n")
        f.write("startFrom       startTime;\n")
        f.write("startTime       0;\n")
        f.write("stopAt          endTime;\n")
        f.write("endTime         1000;\n")
        f.write("deltaT          1;\n")
        f.write("writeControl    timeStep;\n")
        f.write("writeInterval   100;\n\n")
        f.write("functions\n")
        f.write("{\n")
        f.write("    surfaceFieldValue\n")
        f.write("    {\n")
        f.write("        type            surfaceFieldValue;\n")
        f.write("        libs            (fieldFunctionObjects);\n")
        f.write("        writeControl    timeStep;\n")
        f.write("        writeInterval   1;\n")
        f.write("        operation       areaAverage;\n")
        f.write("        fields          (U p);\n")
        f.write("        regionType      patch;\n")
        f.write("        name            inlet;\n")
        f.write("    }\n")
        f.write("}\n\n")
        f.write("// Applied pressure gradient: {:.2f} Pa across domain\n".format(
            dp_val))
        f.write("// * * * * * * * * * * * * * * * * * * * * * * //\n")


def write_fv_schemes(dirpath):
    """Write OpenFOAM fvSchemes file."""
    fpath = os.path.join(dirpath, "system", "fvSchemes")
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w") as f:
        f.write("FoamFile\n")
        f.write("{\n")
        f.write("    version     2.0;\n")
        f.write("    format      ascii;\n")
        f.write("    class       dictionary;\n")
        f.write("    location    \"system\";\n")
        f.write("    object      fvSchemes;\n")
        f.write("}\n")
        f.write("// * * * * * * * * * * * * * * * * * * * * * * //\n\n")
        f.write("ddtSchemes\n")
        f.write("{\n")
        f.write("    default         steadyState;\n")
        f.write("}\n\n")
        f.write("gradSchemes\n")
        f.write("{\n")
        f.write("    default         Gauss linear;\n")
        f.write("    grad(U)         cellLimited Gauss linear 1;\n")
        f.write("}\n\n")
        f.write("divSchemes\n")
        f.write("{\n")
        f.write("    default         none;\n")
        f.write("    div(phi,U)      bounded Gauss linearUpwind grad(U);\n")
        f.write("    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n")
        f.write("}\n\n")
        f.write("laplacianSchemes\n")
        f.write("{\n")
        f.write("    default         Gauss linear corrected;\n")
        f.write("}\n\n")
        f.write("interpolationSchemes\n")
        f.write("{\n")
        f.write("    default         linear;\n")
        f.write("}\n\n")
        f.write("snGradSchemes\n")
        f.write("{\n")
        f.write("    default         corrected;\n")
        f.write("}\n\n")
        f.write("// * * * * * * * * * * * * * * * * * * * * * * //\n")


def write_surface_field_value(dirpath, label, dp_val, U_ss):
    """Write surfaceFieldValue output in OpenFOAM postProcessing format."""
    post_dir = os.path.join(dirpath, "postProcessing", "surfaceFieldValue", "0")
    os.makedirs(post_dir, exist_ok=True)
    fpath = os.path.join(post_dir, "surfaceFieldValue.dat")
    with open(fpath, "w") as f:
        f.write("# Surface field value : surfaceFieldValue\n")
        f.write("# Operation           : areaAverage\n")
        f.write("# Region type         : patch\n")
        f.write("# Case                : {}\n".format(label))
        f.write("# Patches             : (inlet outlet)\n")
        f.write("# Solver              : simpleFoam\n")
        f.write("#\n")
        f.write(
            "# Time"
            "                    "
            "areaAverage(inlet,U)"
            "                        "
            "areaAverage(outlet,U)"
            "                       "
            "areaAverage(inlet,p)"
            "    "
            "areaAverage(outlet,p)\n"
        )
        for t in TIMES:
            frac = 1.0 - math.exp(-t / TAU)
            Ux_in = U_ss * frac
            Uy_in = U_ss * 1.2e-4 * frac
            Ux_out = Ux_in * (1.0 - 2.0e-4)
            Uy_out = -Uy_in * 0.5
            f.write(
                "{:<22.6f}"
                "({:.8e} {:.8e} {:.8e})  "
                "({:.8e} {:.8e} {:.8e})  "
                "{:.8e}    {:.8e}\n".format(
                    t,
                    Ux_in, Uy_in, 0.0,
                    Ux_out, Uy_out, 0.0,
                    dp_val, 0.0,
                )
            )


def main():
    base = "/data/cases"
    os.makedirs(base, exist_ok=True)

    # ---- Write geometry file ----
    geom_path = os.path.join(base, "geometry.dat")
    with open(geom_path, "w") as f:
        f.write("# Porous medium geometry parameters\n")
        f.write("# 2D packed bed of randomly distributed circular particles\n")
        f.write("#\n")
        f.write("# key                   value       unit\n")
        f.write("domain_length           4.0e-03     m\n")
        f.write("domain_height           2.0e-03     m\n")
        f.write("particle_diameter       2.0e-04     m\n")
        f.write("porosity                0.5567      -\n")

    # ---- Mesh convergence study ----
    for nx, ny in MESHES:
        case_name = "mesh_{}x{}".format(nx, ny)
        case_dir = os.path.join(base, case_name)
        h = L / nx
        k_app = K_TRUE + C_MESH * (h ** P_CONV)
        U_ss = forchheimer_velocity(MESH_DP, k_app)
        write_transport_properties(case_dir)
        write_control_dict(case_dir, MESH_DP)
        write_fv_schemes(case_dir)
        write_surface_field_value(
            case_dir,
            "{} (mesh convergence study)".format(case_name),
            MESH_DP,
            U_ss,
        )

    # ---- Pressure sweep study (grid-converged mesh) ----
    for dp_val in PRESSURES:
        case_name = "dp_{:06.2f}".format(dp_val)
        case_dir = os.path.join(base, case_name)
        U_ss = forchheimer_velocity(dp_val, K_TRUE)
        write_transport_properties(case_dir)
        write_control_dict(case_dir, dp_val)
        write_fv_schemes(case_dir)
        write_surface_field_value(
            case_dir,
            "{} (pressure sweep, grid-converged mesh)".format(case_name),
            dp_val,
            U_ss,
        )

    # ---- Write README ----
    readme_path = os.path.join(base, "README.txt")
    with open(readme_path, "w") as f:
        f.write(
            "OpenFOAM Post-Processing Data\n"
            "=============================\n"
            "Single-phase flow through a 2D packed-bed porous medium.\n\n"
            "Case structure follows standard OpenFOAM conventions:\n"
            "  <case>/constant/transportProperties  -- fluid properties\n"
            "  <case>/system/controlDict             -- solver settings\n"
            "  <case>/system/fvSchemes               -- numerical schemes\n"
            "  <case>/postProcessing/surfaceFieldValue/0/surfaceFieldValue.dat\n"
            "                                        -- patch-averaged data\n\n"
            "Geometry:\n"
            "  2D rectangular domain with randomly packed circular particles.\n"
            "  Physical dimensions and packing parameters in geometry.dat.\n\n"
            "Solver: simpleFoam (steady-state, incompressible, laminar)\n\n"
            "Studies:\n"
            "  mesh_*  -- mesh convergence study (3 resolutions, same BCs)\n"
            "             Refinement ratio between successive meshes: 2\n"
            "  dp_*    -- pressure-drop sweep on grid-converged mesh\n"
            "             Covers linear to inertia-dominated flow regimes\n\n"
            "surfaceFieldValue.dat format:\n"
            "  Lines starting with '#' are comments.\n"
            "  Data columns: Time, areaAverage(inlet,U), areaAverage(outlet,U),\n"
            "                areaAverage(inlet,p), areaAverage(outlet,p)\n"
            "  Vector quantities are in parentheses: (Ux Uy Uz)\n"
            "  Primary flow direction is x.\n"
            "  Simulations run to steady state; the final time row is converged.\n"
        )

    print("Data generation complete:")
    for d in sorted(os.listdir(base)):
        full = os.path.join(base, d)
        if os.path.isdir(full):
            print("  {}".format(d))


if __name__ == "__main__":
    main()
