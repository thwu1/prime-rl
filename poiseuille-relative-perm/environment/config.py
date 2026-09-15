"""Configuration for two-phase Poiseuille flow relative permeability analysis."""

# Channel geometry
H = 1.0        # Channel height [m]

# Flow driving force
G = 1.0        # Pressure gradient magnitude, -dP/dx [Pa/m]

# Phase 1 (wetting phase) properties
MU1 = 1.0      # Dynamic viscosity of phase 1 [Pa.s]

# Parametric study: viscosity ratios mu2/mu1
VISCOSITY_RATIOS = [1.0, 2.0, 5.0, 10.0, 20.0]

# Parametric study: wetting phase saturations Sw = h1/H
SATURATIONS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

# Convergence study parameters
CONV_MESH_SIZES = [32, 64, 128, 256]
CONV_SW = 0.3          # Saturation for convergence study
CONV_MU_RATIO = 5.0    # Viscosity ratio for convergence study
