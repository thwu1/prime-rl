#!/bin/bash

set -e

cd /app/sim

# ---- Fix CMakeLists.txt ----
sed -i 's/find_package(Eigen REQUIRED)/find_package(Eigen3 REQUIRED)/' CMakeLists.txt
sed -i 's/Eigen::eigen/Eigen3::Eigen/' CMakeLists.txt

# ---- Fix integrator.cpp ----
# 1) Negate the gamma vector in the initial-acceleration RHS
sed -i 's/rhs\.tail(nc) = gam;/rhs.tail(nc) = -gam;/' src/integrator.cpp

# 2) Evaluate the dynamics constraint Jacobian at the alpha-weighted state
sed -i 's/Phi_q_dyn = model_\.constraintJacobian(q_new)/Phi_q_dyn = model_.constraintJacobian(q_af)/' src/integrator.cpp

# 3) Scale the mass-matrix block of the tangent by (1 - alpha_m)
sed -i 's/J\.topLeftCorner(nq, nq) = M;/J.topLeftCorner(nq, nq) = (1.0 - am) * M;/' src/integrator.cpp

# ---- Build ----
mkdir -p build && cd build
cmake .. && make -j"$(nproc)"

# ---- Run simulation ----
mkdir -p /app/results
./sim -1.0471975511965976 -0.7853981633974483 0.0 0.0 0.9 0.001 1.0 \
      /app/results/trajectory.csv

echo "Solution applied and simulation complete."
