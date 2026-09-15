cmake_minimum_required(VERSION 3.5)
project(eval_validation)
set(CMAKE_BUILD_TYPE Release)

# Build testdriver only (implementation library is pre-built separately)
add_subdirectory(src/testdriver)
