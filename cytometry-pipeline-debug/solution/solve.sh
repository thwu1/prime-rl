#!/bin/bash

# Fix all five defects in the flow cytometry analysis pipeline.
# Each fix targets a specific domain-knowledge error in the R source files.
# Defects are coupled: fixing upstream issues reveals downstream failures.

cd /app

# ============================================================================
# Defect 1: FCS parser byte order mapping is reversed.
#
# The FCS 3.0 spec defines $BYTEORD as the byte significance order:
#   "4,3,2,1" means byte 4 is most significant -> big-endian
#   "1,2,3,4" means byte 1 is most significant -> little-endian
#
# The code had them backwards, causing all float values to be garbage
# when reading the binary DATA segment.
# ============================================================================
python3 -c "
with open('fcs_parser.R', 'r') as f:
    content = f.read()

content = content.replace(
    '\"4,3,2,1\" = \"little\"',
    '\"4,3,2,1\" = \"big\"'
)
content = content.replace(
    '\"1,2,3,4\" = \"big\"',
    '\"1,2,3,4\" = \"little\"'
)

with open('fcs_parser.R', 'w') as f:
    f.write(content)
print('Fixed byte order mapping in fcs_parser.R')
"

# ============================================================================
# Defect 2: Spillover matrix parsed in column-major order.
#
# The FCS \$SPILLOVER keyword stores matrix values row-by-row:
#   n, ch1, ..., chN, m11, m12, ..., m1N, m21, ..., mNN
#
# R's matrix() fills column-by-column by default (byrow=FALSE).
# This effectively transposes the spillover matrix, causing
# incorrect cross-channel compensation values.
# ============================================================================
python3 -c "
with open('compensation.R', 'r') as f:
    content = f.read()

content = content.replace(
    'matrix(values, nrow = n, ncol = n)',
    'matrix(values, nrow = n, ncol = n, byrow = TRUE)'
)

with open('compensation.R', 'w') as f:
    f.write(content)
print('Fixed spillover matrix row-major parsing in compensation.R')
"

# ============================================================================
# Defect 3: Compensation multiplies by spillover instead of its inverse.
#
# The spillover matrix S relates measured (m) to true (t) fluorescence:
#   m = t * S
# Therefore compensation (recovering t from m) requires:
#   t = m * S^{-1}  (multiply by the inverse of S)
#
# The code was doing m * S, which amplifies spectral overlap instead of
# removing it.
# ============================================================================
python3 -c "
with open('compensation.R', 'r') as f:
    content = f.read()

content = content.replace(
    'fl_data %*% spillover_matrix',
    'fl_data %*% solve(spillover_matrix)'
)

with open('compensation.R', 'w') as f:
    f.write(content)
print('Fixed compensation to use matrix inverse in compensation.R')
"

# ============================================================================
# Defects 4-5: Logicle transform has two coupled issues in transforms.R.
#
# (4) Sign error in root-finding equation for parameter d.
#     The equation 2*(ln(d) - ln(b)) + b*(x1 - x0) = 0 is correct,
#     but code uses b*(x0 - x1) which flips the sign, giving wrong d.
#
# (5) logicle_inverse uses a single-step secant approximation that does
#     not converge to the correct root. Issues:
#     - No iteration loop (single correction step is insufficient)
#     - Uses finite-difference derivative instead of analytical B'(y)
#     - Maps all negative inputs to y=0 instead of using the c_*exp(-dy)
#       term to estimate the starting point in the negative branch
#     - Clamps output to [0,1] range, discarding the linearization region
#       mapping for near-zero and negative data values
#
#     Replaced with iterative Newton's method:
#     B(y) = a*exp(by) - c*exp(-dy) + f
#     B'(y) = a*b*exp(by) + c*d*exp(-dy)
#     y_{n+1} = y_n - (B(y_n) - x) / B'(y_n)
#
#     With initial guesses:
#     x > 0: y_0 = max(ln(x/a)/b, x1)   (dominant positive exponential)
#     x < 0: y_0 = min(-ln(-x/c)/d, x1) (dominant negative exponential)
#     x = 0: y_0 = x1                    (zero crossing of biexponential)
# ============================================================================
python3 /solution/fix_transforms.py

echo "All five defects fixed. Pipeline should now produce correct results."
