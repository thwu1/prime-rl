cmake_minimum_required(VERSION 3.16)
project(sokoban_solver LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(solver solver.cpp)
target_compile_options(solver PRIVATE -O2 -Wall -Wextra)
