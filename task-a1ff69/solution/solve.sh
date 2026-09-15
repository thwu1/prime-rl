#!/bin/bash

cd /app

# --- Phase 1: Diagnose and fix all numerical defects ---

# Fix 1: CalcPressureForElems - Gruneisen EOS coefficient
# The Gruneisen parameter Gamma_0 = gamma - 1 = 2/3 for monatomic ideal gas (gamma=5/3).
# Buggy code uses 3/4 instead of 2/3.
sed -i 's|Real_t c1s = Real_t(3\.0)/Real_t(4\.0)|Real_t c1s = Real_t(2.0)/Real_t(3.0)|' lulesh.cc

# Fix 2: CalcEnergyForElems - trapezoidal corrector weight
# The intermediate energy update uses trapezoidal quadrature with weight 4 on the
# half-step pressure. Buggy code uses weight 3 instead of 4.
sed -i 's|- Real_t(3\.0)\*(pHalfStep\[i\] + q_new\[i\]))|- Real_t(4.0)*(pHalfStep[i] + q_new[i]))|' lulesh.cc

# Fix 3: CalcEnergyForElems - Simpson corrector weights
# The final energy corrector uses Simpson's rule with weights (7, -8, 1)/6.
# Buggy code has swapped the 7 and 8 coefficients.
sed -i 's|e_new\[i\] = e_new\[i\] - (  Real_t(8\.0)\*(p_old\[i\]|e_new[i] = e_new[i] - (  Real_t(7.0)*(p_old[i]|' lulesh.cc
sed -i 's|- Real_t(7\.0)\*(pHalfStep\[i\] + q_new\[i\])|- Real_t(8.0)*(pHalfStep[i] + q_new[i])|' lulesh.cc

# Fix 4: Domain constructor (lulesh-init.cc) - hourglass coefficient
# The anti-hourglass damping coefficient m_hgcoef should be 3.0 (standard Flanagan-
# Belytschko value). Buggy code uses 30.0, causing 10x excessive mesh damping.
sed -i 's|m_hgcoef(Real_t(30\.0))|m_hgcoef(Real_t(3.0))|' lulesh-init.cc

# Fix 5: CalcMonotonicQRegionForElems - monotonic Q limiter sign
# The linear artificial viscosity uses (1 - phi) as limiter factor: phi=0 at
# discontinuities gives full viscosity, phi=1 in smooth regions gives zero.
# Buggy code uses (1 + phixi) for xi-direction, doubling viscosity in smooth regions
# and breaking the 3-fold symmetry of the Sedov blast.
sed -i 's|delvxxi   \* (Real_t(1\.) + phixi)|delvxxi   * (Real_t(1.) - phixi)|' lulesh.cc

# Rebuild
make clean 2>/dev/null
make 2>&1

# Quick verification of primary test cases
echo "=== Verification: -s 10 -i 100 ==="
./lulesh2.0 -s 10 -i 100

echo ""
echo "=== Verification: -s 15 -i 50 ==="
./lulesh2.0 -s 15 -i 50

# --- Phase 2: Deploy and run GCI verification framework ---

cp /solution/gci_helper.py /app/gci_analysis.py
chmod +x /app/gci_analysis.py

echo ""
echo "=== GCI Verification Analysis ==="
python3 /app/gci_analysis.py
