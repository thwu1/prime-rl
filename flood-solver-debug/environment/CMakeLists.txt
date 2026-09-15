cmake_minimum_required(VERSION 3.10)
project(FloodSolver LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(flood_solver
    src/main.cpp
    src/solver.cpp
)

target_include_directories(flood_solver PRIVATE src)

install(TARGETS flood_solver DESTINATION bin)
