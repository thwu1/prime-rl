cmake_minimum_required(VERSION 3.16)
project(incircle_test CXX)

set(CMAKE_CXX_STANDARD 17)
add_compile_options(-O2 -frounding-math)

# Test harness — standard C++ only, no external libs
add_executable(test_incircle test_incircle.cpp)

# MPFR verification tool — needs libmpfr and libgmp
find_library(MPFR_LIB mpfr REQUIRED)
find_library(GMP_LIB gmp REQUIRED)
add_executable(verify_mpfr verify_mpfr.cpp)
target_link_libraries(verify_mpfr ${MPFR_LIB} ${GMP_LIB})
