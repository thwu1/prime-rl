cmake_minimum_required(VERSION 3.14)
project(dgemm_benchmark LANGUAGES C CXX)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# Approximate peak speed in GF/s (used only for display, not for pass/fail)
set(MAX_SPEED 20 CACHE STRING "Approximate peak speed in GF/s")

option(ALL_SIZES "Test an extended set of sizes; takes more CPU time." OFF)

# Enable native architecture optimizations for all targets
add_compile_options(-march=native)

# Benchmark harness (C++ object library)
add_library(benchmark OBJECT benchmark.cpp)
target_compile_definitions(benchmark PRIVATE MAX_SPEED=${MAX_SPEED} $<$<BOOL:${ALL_SIZES}>:ALL_SIZES>)
target_compile_features(benchmark PRIVATE cxx_std_11)

# Build each DGEMM variant as a separate benchmark executable
foreach(BENCH IN ITEMS naive blocked blas)
    add_executable(benchmark-${BENCH} dgemm-${BENCH}.c)
    target_link_libraries(benchmark-${BENCH} PRIVATE benchmark openblas)
    target_compile_features(benchmark-${BENCH} PRIVATE c_std_11 c_restrict)
endforeach()
