"""Tests for CIF validation engine (cifcheck.py).

"""

import pytest
import json
import subprocess
import tempfile
import os
import math
import shutil

# ---------------------------------------------------------------------------
# CIF test data
# ---------------------------------------------------------------------------

# Orthorhombic structure with all correct values -- should produce zero alerts
# a=10, b=12, c=8, alpha=beta=gamma=90 => V=960
# C6 H8 O2 => MW=112.128, Z=8 => D=1.55158
CIF_GOOD = """\
data_good

_chemical_formula_sum            'C6 H8 O2'
_chemical_formula_weight          112.13
_cell_length_a                    10.000
_cell_length_b                    12.000
_cell_length_c                    8.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      960.0
_cell_formula_units_Z             8
_exptl_crystal_density_diffrn     1.552

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1 C 0.100 0.200 0.300 0.0250 Uani
C2 C 0.200 0.300 0.400 0.0200 Uani
C3 C 0.300 0.100 0.200 0.0220 Uani
C4 C 0.150 0.250 0.350 0.0240 Uani
C5 C 0.250 0.350 0.450 0.0207 Uani
C6 C 0.350 0.150 0.250 0.0230 Uani
O1 O 0.400 0.100 0.200 0.0220 Uani
O2 O 0.500 0.200 0.300 0.0230 Uani
H1 H 0.110 0.210 0.310 0.030 Uiso
H2 H 0.210 0.310 0.410 0.028 Uiso
H3 H 0.310 0.110 0.210 0.029 Uiso
H4 H 0.410 0.110 0.210 0.031 Uiso
H5 H 0.120 0.220 0.320 0.030 Uiso
H6 H 0.220 0.320 0.420 0.028 Uiso
H7 H 0.320 0.120 0.220 0.029 Uiso
H8 H 0.420 0.120 0.220 0.031 Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1 0.0280 0.0240 0.0230 0.0010 0.0010 0.0010
C2 0.0220 0.0190 0.0190 0.0010 0.0000 0.0010
C3 0.0240 0.0210 0.0210 0.0010 0.0010 0.0000
C4 0.0270 0.0230 0.0220 0.0010 0.0010 0.0010
C5 0.0230 0.0200 0.0190 0.0010 0.0000 0.0010
C6 0.0250 0.0220 0.0220 0.0010 0.0010 0.0000
O1 0.0240 0.0210 0.0210 0.0010 0.0010 0.0010
O2 0.0250 0.0220 0.0220 0.0010 0.0010 0.0010
"""

# Wrong molecular weight: MW_rep=125.00 but MW_calc=112.128
# => ALERT 043: |112.128-125|/125*100=10.30% => Level A
# => ALERT 046: D_zmw=8*125/(960*0.602214)=1.7296 vs D_rep=1.552 => 11.44% => Level A
CIF_WRONG_MW = """\
data_wrong_mw

_chemical_formula_sum            'C6 H8 O2'
_chemical_formula_weight          125.00
_cell_length_a                    10.000
_cell_length_b                    12.000
_cell_length_c                    8.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      960.0
_cell_formula_units_Z             8
_exptl_crystal_density_diffrn     1.552

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1 C 0.100 0.200 0.300 0.025 Uani
O1 O 0.400 0.100 0.200 0.022 Uani
H1 H 0.110 0.210 0.310 0.030 Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1 0.028 0.024 0.023 0.001 0.001 0.001
O1 0.024 0.021 0.021 0.001 0.001 0.001
"""

# Wrong density: D_rep=1.700 but D_calc=1.55158
# => ALERT 044: |1.55158-1.700|/1.700*100 = 8.73% => Level B
# => ALERT 046: D_zmw=8*112.13/(960*0.602214)=1.55161 vs 1.700 => 8.73% => Level B
CIF_WRONG_DENSITY = """\
data_wrong_density

_chemical_formula_sum            'C6 H8 O2'
_chemical_formula_weight          112.13
_cell_length_a                    10.000
_cell_length_b                    12.000
_cell_length_c                    8.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      960.0
_cell_formula_units_Z             8
_exptl_crystal_density_diffrn     1.700

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1 C 0.100 0.200 0.300 0.025 Uani
O1 O 0.400 0.100 0.200 0.022 Uani
H1 H 0.110 0.210 0.310 0.030 Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1 0.028 0.024 0.023 0.001 0.001 0.001
O1 0.024 0.021 0.021 0.001 0.001 0.001
"""

# No hydrogen atoms in a carbon-containing compound => ALERT 040 Level C
CIF_NO_H = """\
data_no_h

_chemical_formula_sum            'C6 O2'
_chemical_formula_weight          104.06
_cell_length_a                    10.000
_cell_length_b                    12.000
_cell_length_c                    8.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      960.0
_cell_formula_units_Z             8
_exptl_crystal_density_diffrn     1.440

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1 C 0.100 0.200 0.300 0.025 Uani
C2 C 0.200 0.300 0.400 0.020 Uani
C3 C 0.300 0.100 0.200 0.022 Uani
C4 C 0.150 0.250 0.350 0.024 Uani
C5 C 0.250 0.350 0.450 0.021 Uani
C6 C 0.350 0.150 0.250 0.023 Uani
O1 O 0.400 0.100 0.200 0.022 Uani
O2 O 0.500 0.200 0.300 0.023 Uani

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1 0.028 0.024 0.023 0.001 0.001 0.001
C2 0.022 0.019 0.019 0.001 0.000 0.001
C3 0.024 0.021 0.021 0.001 0.001 0.000
C4 0.027 0.023 0.022 0.001 0.001 0.001
C5 0.023 0.020 0.019 0.001 0.000 0.001
C6 0.025 0.022 0.022 0.001 0.001 0.000
O1 0.024 0.021 0.021 0.001 0.001 0.001
O2 0.025 0.022 0.022 0.001 0.001 0.001
"""

# Extreme ADP ratio: C1 has U11=0.120, U22=0.025, U33=0.001 (all off-diag=0)
# Orthorhombic => eigenvalues are [0.001, 0.025, 0.120]
# ratio = sqrt(0.120/0.001) = sqrt(120) = 10.954 => Level A (>5.0)
CIF_BAD_ADP = """\
data_bad_adp

_chemical_formula_sum            'C2 H4 O'
_chemical_formula_weight          44.05
_cell_length_a                    10.000
_cell_length_b                    10.000
_cell_length_c                    10.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      1000.0
_cell_formula_units_Z             20
_exptl_crystal_density_diffrn     1.463

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1 C 0.100 0.200 0.300 0.0487 Uani
C2 C 0.200 0.300 0.400 0.0200 Uani
O1 O 0.300 0.100 0.200 0.0220 Uani
H1 H 0.110 0.210 0.310 0.030 Uiso
H2 H 0.210 0.310 0.410 0.028 Uiso
H3 H 0.310 0.110 0.210 0.029 Uiso
H4 H 0.410 0.110 0.210 0.031 Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1 0.120 0.025 0.001 0.000 0.000 0.000
C2 0.022 0.019 0.019 0.001 0.000 0.001
O1 0.024 0.021 0.021 0.001 0.001 0.001
"""

# Ueq mismatch: C1 has U11=0.030,U22=0.025,U33=0.020 (ortho => Ueq=0.025)
# but reported Ueq=0.035 => diff=0.010 => Level A (>0.005)
CIF_BAD_UEQ = """\
data_bad_ueq

_chemical_formula_sum            'C2 H4 O'
_chemical_formula_weight          44.05
_cell_length_a                    10.000
_cell_length_b                    10.000
_cell_length_c                    10.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      1000.0
_cell_formula_units_Z             20
_exptl_crystal_density_diffrn     1.463

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1 C 0.100 0.200 0.300 0.035 Uani
C2 C 0.200 0.300 0.400 0.020 Uani
O1 O 0.300 0.100 0.200 0.022 Uani
H1 H 0.110 0.210 0.310 0.030 Uiso
H2 H 0.210 0.310 0.410 0.028 Uiso
H3 H 0.310 0.110 0.210 0.029 Uiso
H4 H 0.410 0.110 0.210 0.031 Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1 0.030 0.025 0.020 0.000 0.000 0.000
C2 0.022 0.019 0.019 0.001 0.000 0.001
O1 0.024 0.021 0.021 0.001 0.001 0.001
"""

# Non-positive-definite ADP: C1 has U12=0.019 making 2x2 block NPD
# eigenvalues: [-0.00166, 0.010, 0.03666] => ALERT 211 Level B
CIF_NPD = """\
data_npd

_chemical_formula_sum            'C2 H4 O'
_chemical_formula_weight          44.05
_cell_length_a                    10.000
_cell_length_b                    10.000
_cell_length_c                    10.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      1000.0
_cell_formula_units_Z             20
_exptl_crystal_density_diffrn     1.463

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1 C 0.100 0.200 0.300 0.015 Uani
C2 C 0.200 0.300 0.400 0.020 Uani
O1 O 0.300 0.100 0.200 0.022 Uani
H1 H 0.110 0.210 0.310 0.030 Uiso
H2 H 0.210 0.310 0.410 0.028 Uiso
H3 H 0.310 0.110 0.210 0.029 Uiso
H4 H 0.410 0.110 0.210 0.031 Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1 0.020 0.015 0.010 0.000 0.000 0.019
C2 0.022 0.019 0.019 0.001 0.000 0.001
O1 0.024 0.021 0.021 0.001 0.001 0.001
"""

# Monoclinic cell (glycine-like) to test Ueq in non-orthogonal coordinate system
# a=5.102, b=11.971, c=5.457, beta=111.70
# V = a*b*c*sin(beta) = 309.794
CIF_MONOCLINIC = """\
data_monoclinic

_chemical_formula_sum            'C2 H5 N O2'
_chemical_formula_weight          75.07
_cell_length_a                    5.102
_cell_length_b                    11.971
_cell_length_c                    5.457
_cell_angle_alpha                 90.00
_cell_angle_beta                  111.70
_cell_angle_gamma                 90.00
_cell_volume                      309.80
_cell_formula_units_Z             4
_exptl_crystal_density_diffrn     1.609

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1  C  0.2842  0.1542  0.1873  0.0233  Uani
C2  C  0.3362  0.0474  0.3219  0.0181  Uani
N1  N  0.0929  0.1523  0.2877  0.0230  Uani
O1  O  0.4448  0.0465  0.5736  0.0229  Uani
O2  O  0.2669 -0.0413  0.1935  0.0246  Uani
H1A H  0.2012  0.1555  0.0023  0.028   Uiso
H1B H  0.4416  0.2087  0.2437  0.028   Uiso
H1N H  0.1497  0.1512  0.4635  0.028   Uiso
H2N H -0.0666  0.1120  0.2035  0.028   Uiso
H3N H  0.0629  0.2233  0.2262  0.028   Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1  0.0257  0.0219  0.0201  0.0028  0.0060 -0.0014
C2  0.0172  0.0193  0.0168 -0.0006  0.0053  0.0009
N1  0.0198  0.0276  0.0227  0.0003  0.0091  0.0043
O1  0.0261  0.0258  0.0139  0.0000  0.0041 -0.0006
O2  0.0295  0.0199  0.0209 -0.0032  0.0051 -0.0024
"""

# Formula mismatch: formula says C6 H8 O2 but atom list has N atom
# => ALERT 041 Level C
CIF_FORMULA_MISMATCH = """\
data_formula_mismatch

_chemical_formula_sum            'C6 H8 O2'
_chemical_formula_weight          112.13
_cell_length_a                    10.000
_cell_length_b                    12.000
_cell_length_c                    8.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      960.0
_cell_formula_units_Z             8
_exptl_crystal_density_diffrn     1.552

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1 C 0.100 0.200 0.300 0.025 Uani
O1 O 0.400 0.100 0.200 0.022 Uani
N1 N 0.200 0.300 0.400 0.021 Uani
H1 H 0.110 0.210 0.310 0.030 Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1 0.028 0.024 0.023 0.001 0.001 0.001
O1 0.024 0.021 0.021 0.001 0.001 0.001
N1 0.023 0.020 0.020 0.001 0.000 0.001
"""

# Low density: V=512, C2H6O, Z=2 => D=0.299 => ALERT 049 Level C
CIF_LOW_DENSITY = """\
data_low_density

_chemical_formula_sum            'C2 H6 O'
_chemical_formula_weight          46.07
_cell_length_a                    8.000
_cell_length_b                    8.000
_cell_length_c                    8.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      512.0
_cell_formula_units_Z             2
_exptl_crystal_density_diffrn     0.299

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1 C 0.100 0.200 0.300 0.025 Uani
C2 C 0.200 0.300 0.400 0.020 Uani
O1 O 0.300 0.100 0.200 0.022 Uani
H1 H 0.110 0.210 0.310 0.030 Uiso
H2 H 0.210 0.310 0.410 0.028 Uiso
H3 H 0.310 0.110 0.210 0.029 Uiso
H4 H 0.410 0.110 0.210 0.031 Uiso
H5 H 0.120 0.220 0.320 0.030 Uiso
H6 H 0.220 0.320 0.420 0.028 Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1 0.028 0.024 0.023 0.001 0.001 0.001
C2 0.022 0.019 0.019 0.001 0.000 0.001
O1 0.024 0.021 0.021 0.001 0.001 0.001
"""

# Isotropic non-H atoms: C3, C4, C5 have Uiso (not in aniso loop)
# => 3 isotropic non-H atoms => ALERT 201 Level C
CIF_ISO_ATOMS = """\
data_iso_atoms

_chemical_formula_sum            'C6 H8 O2'
_chemical_formula_weight          112.13
_cell_length_a                    10.000
_cell_length_b                    12.000
_cell_length_c                    8.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      960.0
_cell_formula_units_Z             8
_exptl_crystal_density_diffrn     1.552

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1 C 0.100 0.200 0.300 0.025 Uani
C2 C 0.200 0.300 0.400 0.020 Uani
C3 C 0.300 0.100 0.200 0.022 Uiso
C4 C 0.150 0.250 0.350 0.024 Uiso
C5 C 0.250 0.350 0.450 0.021 Uiso
C6 C 0.350 0.150 0.250 0.023 Uani
O1 O 0.400 0.100 0.200 0.022 Uani
O2 O 0.500 0.200 0.300 0.023 Uani
H1 H 0.110 0.210 0.310 0.030 Uiso
H2 H 0.210 0.310 0.410 0.028 Uiso
H3 H 0.310 0.110 0.210 0.029 Uiso
H4 H 0.410 0.110 0.210 0.031 Uiso
H5 H 0.120 0.220 0.320 0.030 Uiso
H6 H 0.220 0.320 0.420 0.028 Uiso
H7 H 0.320 0.120 0.220 0.029 Uiso
H8 H 0.420 0.120 0.220 0.031 Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1 0.028 0.024 0.023 0.001 0.001 0.001
C2 0.022 0.019 0.019 0.001 0.000 0.001
C6 0.025 0.022 0.022 0.001 0.001 0.000
O1 0.024 0.021 0.021 0.001 0.001 0.001
O2 0.025 0.022 0.022 0.001 0.001 0.001
"""

# CIF with standard uncertainty notation in cell parameters
CIF_WITH_SU = """\
data_with_su

_chemical_formula_sum            'C2 H5 N O2'
_chemical_formula_weight          75.07
_cell_length_a                    5.1020(10)
_cell_length_b                    11.971(2)
_cell_length_c                    5.4570(11)
_cell_angle_alpha                 90
_cell_angle_beta                  111.70(3)
_cell_angle_gamma                 90
_cell_volume                      309.52(11)
_cell_formula_units_Z             4
_exptl_crystal_density_diffrn     1.611

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_adp_type
C1  C  0.2842(3)  0.1542(1)  0.1873(3)  0.0232(4)  Uani
N1  N  0.0929(3)  0.1523(1)  0.2877(3)  0.0230(4)  Uani
O1  O  0.4448(2)  0.0465(1)  0.5736(2)  0.0228(3)  Uani
H1A H  0.2012     0.1555     0.0023     0.028       Uiso

loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_23
_atom_site_aniso_U_13
_atom_site_aniso_U_12
C1  0.0257(8) 0.0219(7) 0.0201(7) 0.0028(6) 0.0060(6) -0.0014(6)
N1  0.0198(7) 0.0276(7) 0.0227(7) 0.0003(5) 0.0091(5)  0.0043(5)
O1  0.0261(6) 0.0258(5) 0.0139(5) 0.0000(4) 0.0041(4) -0.0006(4)
"""

# Minimal CIF with only cell parameters -- should not crash, skip all checks
CIF_MINIMAL = """\
data_minimal

_cell_length_a    10.0
_cell_length_b    10.0
_cell_length_c    10.0
_cell_angle_alpha 90.0
_cell_angle_beta  90.0
_cell_angle_gamma 90.0
"""

# CIF with unknown (non-standard) data items for dictionary validation
CIF_UNKNOWN_TAGS = """\
data_unknown_tags

_cell_length_a                    10.000
_cell_length_b                    10.000
_cell_length_c                    10.000
_cell_angle_alpha                 90.00
_cell_angle_beta                  90.00
_cell_angle_gamma                 90.00
_cell_volume                      1000.0
_custom_experiment_id             'XRD-2024-001'
_nonstandard_quality_indicator    high
_proprietary_software_version     '3.2.1'
"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_cifcheck(cif_content):
    """Run cifcheck.py on a CIF string and return parsed JSON output."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cif', delete=False, dir='/tmp') as f:
        f.write(cif_content)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ['python3', '/app/cifcheck.py', tmp_path],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"cifcheck.py exited with code {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        data = json.loads(result.stdout)
        return data
    finally:
        os.unlink(tmp_path)


def get_alerts_by_code(output, code):
    """Return list of alerts with the given code."""
    return [a for a in output.get('alerts', []) if a.get('code') == code]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutputFormat:
    """Verify JSON output has required structure."""

    def test_has_required_fields(self):
        out = run_cifcheck(CIF_GOOD)
        assert 'data_block' in out
        assert 'alerts' in out
        assert 'computed' in out
        assert isinstance(out['alerts'], list)
        assert isinstance(out['computed'], dict)

    def test_data_block_name(self):
        out = run_cifcheck(CIF_GOOD)
        assert out['data_block'] == 'good'

    def test_computed_has_required_keys(self):
        out = run_cifcheck(CIF_GOOD)
        comp = out['computed']
        assert 'cell_volume' in comp
        assert 'formula_weight' in comp
        assert 'density' in comp
        assert 'ueq' in comp


class TestGoodCIF:
    """A well-formed CIF should produce zero alerts."""

    def test_no_alerts(self):
        out = run_cifcheck(CIF_GOOD)
        assert len(out['alerts']) == 0, (
            f"Expected zero alerts, got: {json.dumps(out['alerts'], indent=2)}"
        )

    def test_cell_volume(self):
        out = run_cifcheck(CIF_GOOD)
        # V = 10 * 12 * 8 = 960.0
        assert abs(out['computed']['cell_volume'] - 960.0) < 0.5

    def test_formula_weight(self):
        out = run_cifcheck(CIF_GOOD)
        # C6 H8 O2 = 6*12.011 + 8*1.008 + 2*15.999 = 112.128
        assert abs(out['computed']['formula_weight'] - 112.128) < 0.1

    def test_density(self):
        out = run_cifcheck(CIF_GOOD)
        # D = 8*112.128 / (960 * 0.602214076) = 1.55158
        assert abs(out['computed']['density'] - 1.5516) < 0.005

    def test_ueq_values(self):
        out = run_cifcheck(CIF_GOOD)
        ueq = out['computed']['ueq']
        # For orthorhombic: Ueq = (U11+U22+U33)/3
        # C1: (0.028+0.024+0.023)/3 = 0.025
        assert abs(ueq['C1'] - 0.025) < 0.001
        # C2: (0.022+0.019+0.019)/3 = 0.020
        assert abs(ueq['C2'] - 0.020) < 0.001


class TestAlert043:
    """MW percentage difference check."""

    def test_wrong_mw_triggers_alert(self):
        out = run_cifcheck(CIF_WRONG_MW)
        alerts = get_alerts_by_code(out, '043')
        assert len(alerts) >= 1, "ALERT 043 should trigger for wrong MW"

    def test_wrong_mw_level_a(self):
        out = run_cifcheck(CIF_WRONG_MW)
        alerts = get_alerts_by_code(out, '043')
        assert alerts[0]['level'] == 'A', (
            f"Expected level A, got {alerts[0]['level']} (value={alerts[0].get('value')})"
        )

    def test_wrong_mw_type(self):
        out = run_cifcheck(CIF_WRONG_MW)
        alerts = get_alerts_by_code(out, '043')
        assert alerts[0]['type'] == 1

    def test_good_cif_no_043(self):
        out = run_cifcheck(CIF_GOOD)
        assert len(get_alerts_by_code(out, '043')) == 0


class TestAlert044And046:
    """Density difference checks (044: calc MW, 046: reported MW)."""

    def test_wrong_density_triggers_044(self):
        out = run_cifcheck(CIF_WRONG_DENSITY)
        alerts = get_alerts_by_code(out, '044')
        assert len(alerts) >= 1, "ALERT 044 should trigger for wrong density"
        # |1.55158 - 1.700| / 1.700 * 100 = 8.73% => Level B
        assert alerts[0]['level'] == 'B'

    def test_wrong_density_triggers_046(self):
        out = run_cifcheck(CIF_WRONG_DENSITY)
        alerts = get_alerts_by_code(out, '046')
        assert len(alerts) >= 1, "ALERT 046 should trigger for wrong density"
        assert alerts[0]['level'] == 'B'

    def test_wrong_mw_044_not_triggered(self):
        """When MW_rep is wrong but D_rep matches D_calc, ALERT 044 should NOT fire."""
        out = run_cifcheck(CIF_WRONG_MW)
        alerts_044 = get_alerts_by_code(out, '044')
        # D_calc = Z*MW_calc/(V*Na*1e-24) = 1.55158; D_rep = 1.552
        # diff = 0.027% < 1.0 => no alert
        assert len(alerts_044) == 0, (
            "ALERT 044 should not fire when D_rep matches D(calc from formula)"
        )

    def test_wrong_mw_046_triggered(self):
        """When MW_rep is wrong, D_zmw != D_rep => ALERT 046 fires."""
        out = run_cifcheck(CIF_WRONG_MW)
        alerts_046 = get_alerts_by_code(out, '046')
        assert len(alerts_046) >= 1, "ALERT 046 should fire for inconsistent MW"
        assert alerts_046[0]['level'] == 'A'


class TestAlert040:
    """No hydrogen in carbon-containing compound."""

    def test_no_h_triggers_040(self):
        out = run_cifcheck(CIF_NO_H)
        alerts = get_alerts_by_code(out, '040')
        assert len(alerts) >= 1, "ALERT 040 should trigger for no-H CIF"
        assert alerts[0]['level'] == 'C'

    def test_good_cif_no_040(self):
        out = run_cifcheck(CIF_GOOD)
        assert len(get_alerts_by_code(out, '040')) == 0


class TestAlert041:
    """Formula element set mismatch."""

    def test_formula_mismatch(self):
        out = run_cifcheck(CIF_FORMULA_MISMATCH)
        alerts = get_alerts_by_code(out, '041')
        assert len(alerts) >= 1, "ALERT 041 should trigger when atom elements differ from formula"
        assert alerts[0]['level'] == 'C'

    def test_good_cif_no_041(self):
        out = run_cifcheck(CIF_GOOD)
        assert len(get_alerts_by_code(out, '041')) == 0


class TestAlert049:
    """Low density check."""

    def test_low_density(self):
        out = run_cifcheck(CIF_LOW_DENSITY)
        alerts = get_alerts_by_code(out, '049')
        assert len(alerts) >= 1, "ALERT 049 should trigger for density < 1.0"
        assert alerts[0]['level'] == 'C'
        assert alerts[0]['value'] < 1.0

    def test_good_cif_no_049(self):
        out = run_cifcheck(CIF_GOOD)
        assert len(get_alerts_by_code(out, '049')) == 0


class TestAlert201:
    """Isotropic non-H atoms."""

    def test_iso_atoms(self):
        out = run_cifcheck(CIF_ISO_ATOMS)
        alerts = get_alerts_by_code(out, '201')
        assert len(alerts) >= 1, "ALERT 201 should trigger for isotropic non-H atoms"
        assert alerts[0]['level'] == 'C'
        # Value should be count of iso non-H atoms (C3, C4, C5 = 3)
        assert alerts[0]['value'] >= 3

    def test_good_cif_no_201(self):
        out = run_cifcheck(CIF_GOOD)
        assert len(get_alerts_by_code(out, '201')) == 0


class TestAlert213:
    """ADP eigenvalue ratio."""

    def test_bad_adp_ratio(self):
        out = run_cifcheck(CIF_BAD_ADP)
        alerts = get_alerts_by_code(out, '213')
        # Find the alert for C1
        c1_alerts = [a for a in alerts if a.get('atom') == 'C1']
        assert len(c1_alerts) >= 1, "ALERT 213 should trigger for C1 with extreme ADP ratio"
        assert c1_alerts[0]['level'] == 'A'
        # sqrt(0.120/0.001) = 10.954
        assert c1_alerts[0]['value'] > 10.0

    def test_bad_adp_has_atom_field(self):
        out = run_cifcheck(CIF_BAD_ADP)
        alerts = get_alerts_by_code(out, '213')
        for a in alerts:
            assert 'atom' in a and a['atom'] is not None

    def test_good_cif_no_213(self):
        out = run_cifcheck(CIF_GOOD)
        assert len(get_alerts_by_code(out, '213')) == 0


class TestAlert224:
    """Ueq mismatch."""

    def test_bad_ueq(self):
        out = run_cifcheck(CIF_BAD_UEQ)
        alerts = get_alerts_by_code(out, '224')
        c1_alerts = [a for a in alerts if a.get('atom') == 'C1']
        assert len(c1_alerts) >= 1, "ALERT 224 should trigger for C1 with Ueq mismatch"
        assert c1_alerts[0]['level'] == 'A'
        # diff = |0.035 - 0.025| = 0.010
        assert c1_alerts[0]['value'] > 0.005

    def test_good_cif_no_224(self):
        out = run_cifcheck(CIF_GOOD)
        assert len(get_alerts_by_code(out, '224')) == 0


class TestAlert211:
    """Non-positive-definite ADP."""

    def test_npd(self):
        out = run_cifcheck(CIF_NPD)
        alerts = get_alerts_by_code(out, '211')
        c1_alerts = [a for a in alerts if a.get('atom') == 'C1']
        assert len(c1_alerts) >= 1, "ALERT 211 should trigger for NPD ADP"
        assert c1_alerts[0]['level'] == 'B'

    def test_npd_no_213(self):
        """NPD atoms should NOT trigger ALERT 213 (ratio is undefined)."""
        out = run_cifcheck(CIF_NPD)
        alerts_213 = get_alerts_by_code(out, '213')
        c1_213 = [a for a in alerts_213 if a.get('atom') == 'C1']
        assert len(c1_213) == 0, "ALERT 213 should be skipped for NPD atoms"

    def test_good_cif_no_211(self):
        out = run_cifcheck(CIF_GOOD)
        assert len(get_alerts_by_code(out, '211')) == 0


class TestAlert060:
    """Unknown CIF data items detected via dictionary validation."""

    def test_unknown_tags_trigger_060(self):
        """Non-standard CIF data items must trigger ALERT 060."""
        out = run_cifcheck(CIF_UNKNOWN_TAGS)
        alerts = get_alerts_by_code(out, '060')
        assert len(alerts) >= 1, "ALERT 060 should trigger for unknown CIF data items"
        assert alerts[0]['level'] == 'C'
        # 3 unknown tags: _custom_experiment_id, _nonstandard_quality_indicator,
        # _proprietary_software_version
        assert alerts[0]['value'] >= 3

    def test_good_cif_no_060(self):
        """Standard CIF data items should not trigger ALERT 060."""
        out = run_cifcheck(CIF_GOOD)
        assert len(get_alerts_by_code(out, '060')) == 0, (
            "ALERT 060 should not fire for standard CIF data items"
        )

    def test_unknown_tags_cell_volume_still_computed(self):
        """Unknown tags should not prevent computation of known quantities."""
        out = run_cifcheck(CIF_UNKNOWN_TAGS)
        assert abs(out['computed'].get('cell_volume', 0) - 1000.0) < 1.0

    def test_dictionary_file_exists(self):
        """The dictionary file must be present for dictionary validation."""
        assert os.path.exists('/app/cif_core_subset.dic'), (
            "cif_core_subset.dic must exist in /app/"
        )

    def test_all_su_tags_recognized(self):
        """CIF_WITH_SU uses standard tags -- none should be unknown."""
        out = run_cifcheck(CIF_WITH_SU)
        alerts_060 = get_alerts_by_code(out, '060')
        assert len(alerts_060) == 0, (
            f"Standard tags in SU CIF triggered ALERT 060: {alerts_060}"
        )


class TestMonoclinicUeq:
    """Ueq computation in a monoclinic cell requires the full metric tensor."""

    def test_monoclinic_no_224_alerts(self):
        """Properly computed Ueq should match reported values (no ALERT 224)."""
        out = run_cifcheck(CIF_MONOCLINIC)
        alerts = get_alerts_by_code(out, '224')
        assert len(alerts) == 0, (
            f"Monoclinic Ueq should match reported values, got alerts: "
            f"{json.dumps(alerts, indent=2)}"
        )

    def test_monoclinic_ueq_c1(self):
        """C1 in monoclinic cell: Ueq = 0.02327 (hand-calculated)."""
        out = run_cifcheck(CIF_MONOCLINIC)
        ueq = out['computed']['ueq']
        assert 'C1' in ueq
        assert abs(ueq['C1'] - 0.02327) < 0.001

    def test_monoclinic_cell_volume(self):
        out = run_cifcheck(CIF_MONOCLINIC)
        # V = a*b*c*sin(beta) = 5.102*11.971*5.457*sin(111.70) = 309.794
        assert abs(out['computed']['cell_volume'] - 309.8) < 1.0

    def test_monoclinic_formula_weight(self):
        out = run_cifcheck(CIF_MONOCLINIC)
        # C2 H5 N O2 = 2*12.011 + 5*1.008 + 14.007 + 2*15.999 = 75.067
        assert abs(out['computed']['formula_weight'] - 75.067) < 0.1


class TestSUParsing:
    """Verify standard uncertainty notation is handled correctly."""

    def test_su_cell_volume(self):
        """Cell params with SU notation like 5.1020(10) should parse correctly."""
        out = run_cifcheck(CIF_WITH_SU)
        # V = 5.1020 * 11.971 * 5.4570 * sin(111.70) ~ 309.8
        assert abs(out['computed']['cell_volume'] - 309.8) < 1.0

    def test_su_ueq_values(self):
        """Uij values with SU notation should parse correctly."""
        out = run_cifcheck(CIF_WITH_SU)
        ueq = out['computed'].get('ueq', {})
        assert 'C1' in ueq
        assert abs(ueq['C1'] - 0.0233) < 0.001


class TestMinimalCIF:
    """CIF with only cell parameters should not crash and skip formula checks."""

    def test_no_crashes(self):
        out = run_cifcheck(CIF_MINIMAL)
        assert 'data_block' in out
        assert 'alerts' in out
        assert isinstance(out['alerts'], list)

    def test_cell_volume_computed(self):
        out = run_cifcheck(CIF_MINIMAL)
        assert abs(out['computed'].get('cell_volume', 0) - 1000.0) < 1.0

    def test_no_formula_related_alerts(self):
        """Without formula data, formula-dependent checks should be skipped."""
        out = run_cifcheck(CIF_MINIMAL)
        for a in out['alerts']:
            assert a['code'] not in ('040', '041', '043', '044', '046', '049')


class TestDynamicRuleLoading:
    """Verify that modifying check_rules.dat changes validation behavior."""

    def test_threshold_change_affects_level(self):
        """Changing the A-threshold for ALERT 043 should change the severity."""
        shutil.copy('/app/check_rules.dat', '/tmp/check_rules_backup.dat')
        try:
            # Original: 043 threshold is 0.1/1.0/10.0
            # CIF_WRONG_MW: MW diff ~10.3% => Level A (>10.0)
            out1 = run_cifcheck(CIF_WRONG_MW)
            alerts1 = get_alerts_by_code(out1, '043')
            assert len(alerts1) >= 1
            assert alerts1[0]['level'] == 'A'

            # Change 043 threshold to 0.1/1.0/15.0
            with open('/app/check_rules.dat') as f:
                content = f.read()
            content = content.replace('0.1/1.0/10.0', '0.1/1.0/15.0')
            with open('/app/check_rules.dat', 'w') as f:
                f.write(content)

            # Now MW diff ~10.3% < 15.0 but > 1.0 => Level B
            out2 = run_cifcheck(CIF_WRONG_MW)
            alerts2 = get_alerts_by_code(out2, '043')
            assert len(alerts2) >= 1
            assert alerts2[0]['level'] == 'B', (
                f"After changing A-threshold to 15.0, expected level B, "
                f"got {alerts2[0]['level']}"
            )
        finally:
            shutil.copy('/tmp/check_rules_backup.dat', '/app/check_rules.dat')

    def test_removed_rule_no_alert(self):
        """Removing ALERT 040 rule from check_rules.dat should prevent that alert."""
        shutil.copy('/app/check_rules.dat', '/tmp/check_rules_backup2.dat')
        try:
            with open('/app/check_rules.dat') as f:
                lines = f.readlines()
            with open('/app/check_rules.dat', 'w') as f:
                for line in lines:
                    if not line.strip().startswith('040'):
                        f.write(line)

            out = run_cifcheck(CIF_NO_H)
            assert len(get_alerts_by_code(out, '040')) == 0, (
                "ALERT 040 should not fire after removing its rule"
            )
        finally:
            shutil.copy('/tmp/check_rules_backup2.dat', '/app/check_rules.dat')


class TestDynamicWeightLoading:
    """Verify that modifying element_weights.cif changes computed weights."""

    def test_modified_weight_changes_mw(self):
        """Changing the carbon weight in element_weights.cif should change MW."""
        shutil.copy('/app/element_weights.cif', '/tmp/weights_backup.cif')
        try:
            # Original C weight is 12.011
            out1 = run_cifcheck(CIF_GOOD)
            mw1 = out1['computed']['formula_weight']
            assert abs(mw1 - 112.128) < 0.1

            # Change C weight to 13.000
            with open('/app/element_weights.cif') as f:
                content = f.read()
            content = content.replace('C    12.011', 'C    13.000')
            with open('/app/element_weights.cif', 'w') as f:
                f.write(content)

            # C6 H8 O2 with C=13.000: 6*13.000 + 8*1.008 + 2*15.999 = 118.062
            out2 = run_cifcheck(CIF_GOOD)
            mw2 = out2['computed']['formula_weight']
            assert abs(mw2 - 118.062) < 0.1, (
                f"With C=13.000, expected MW~118.062, got {mw2}"
            )
        finally:
            shutil.copy('/tmp/weights_backup.cif', '/app/element_weights.cif')


class TestBatchPipeline:
    """Test cifbatch.sh batch validation pipeline with jq and sqlite3."""

    @pytest.fixture(autouse=True)
    def setup_batch(self, tmp_path):
        """Create batch directory with test CIF files and clean DB."""
        self.batch_dir = tmp_path / "batch_cifs"
        self.batch_dir.mkdir()
        (self.batch_dir / "good.cif").write_text(CIF_GOOD)
        (self.batch_dir / "wrong_mw.cif").write_text(CIF_WRONG_MW)
        (self.batch_dir / "no_h.cif").write_text(CIF_NO_H)

        if os.path.exists('/app/validation.db'):
            os.remove('/app/validation.db')
        yield
        if os.path.exists('/app/validation.db'):
            os.remove('/app/validation.db')

    def _run_batch(self):
        result = subprocess.run(
            ['bash', '/app/cifbatch.sh', str(self.batch_dir)],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, (
            f"cifbatch.sh failed: stderr={result.stderr}"
        )
        return result

    def test_jq_available(self):
        """jq must be available for the batch pipeline."""
        result = subprocess.run(['which', 'jq'], capture_output=True, text=True)
        assert result.returncode == 0, "jq not found in PATH"

    def test_sqlite3_available(self):
        """sqlite3 must be available for the batch pipeline."""
        result = subprocess.run(['which', 'sqlite3'], capture_output=True, text=True)
        assert result.returncode == 0, "sqlite3 not found in PATH"

    def test_database_created(self):
        """cifbatch.sh must create /app/validation.db."""
        self._run_batch()
        assert os.path.exists('/app/validation.db'), "validation.db not created"

    def test_database_schema(self):
        """Database must have results table with correct columns."""
        self._run_batch()
        import sqlite3 as sql3
        conn = sql3.connect('/app/validation.db')
        cursor = conn.execute("PRAGMA table_info(results)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {'filename', 'data_block', 'alert_count', 'max_severity',
                    'cell_volume', 'formula_weight', 'density', 'alerts_json'}
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_database_row_count(self):
        """Database must have one row per CIF file processed."""
        self._run_batch()
        import sqlite3 as sql3
        conn = sql3.connect('/app/validation.db')
        cursor = conn.execute("SELECT COUNT(*) FROM results")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 3, f"Expected 3 rows, got {count}"

    def test_max_severity_good(self):
        """good.cif should have max_severity NONE."""
        self._run_batch()
        import sqlite3 as sql3
        conn = sql3.connect('/app/validation.db')
        cursor = conn.execute(
            "SELECT max_severity FROM results WHERE filename='good.cif'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "good.cif not in database"
        assert row[0] == 'NONE', f"good.cif max_severity={row[0]}, expected NONE"

    def test_max_severity_wrong_mw(self):
        """wrong_mw.cif should have max_severity A."""
        self._run_batch()
        import sqlite3 as sql3
        conn = sql3.connect('/app/validation.db')
        cursor = conn.execute(
            "SELECT max_severity FROM results WHERE filename='wrong_mw.cif'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "wrong_mw.cif not in database"
        assert row[0] == 'A', f"wrong_mw.cif max_severity={row[0]}, expected A"

    def test_summary_json_structure(self):
        """stdout must be valid JSON with required keys."""
        result = self._run_batch()
        summary = json.loads(result.stdout.strip())
        assert summary['total_files'] == 3
        assert summary['files_with_alerts'] == 2
        assert 'alert_counts' in summary
        counts = summary['alert_counts']
        assert 'A' in counts and 'B' in counts and 'C' in counts

    def test_summary_alert_counts(self):
        """Alert counts must reflect totals across all files."""
        result = self._run_batch()
        summary = json.loads(result.stdout.strip())
        counts = summary['alert_counts']
        # wrong_mw.cif: ALERT 043(A) + ALERT 046(A) = 2 A-level
        assert counts['A'] >= 2, f"Expected >=2 A-level alerts, got {counts['A']}"
        # no_h.cif: ALERT 040(C) = 1 C-level
        assert counts['C'] >= 1, f"Expected >=1 C-level alerts, got {counts['C']}"

    def test_cell_volume_stored(self):
        """cell_volume must be stored in the database for files with cell data."""
        self._run_batch()
        import sqlite3 as sql3
        conn = sql3.connect('/app/validation.db')
        cursor = conn.execute(
            "SELECT cell_volume FROM results WHERE filename='good.cif'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None and row[0] is not None
        assert abs(row[0] - 960.0) < 1.0, f"cell_volume={row[0]}, expected ~960"
