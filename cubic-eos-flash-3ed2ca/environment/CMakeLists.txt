cmake_minimum_required(VERSION 3.16)
project(PRFlashSolver CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(flash_solver
    src/main.cpp
    src/pr_eos.cpp
    src/flash_engne.cpp
)

target_include_directories(flash_solver PRIVATE src)
target_compile_options(flash_solver PRIVATE -O2 -Wall)
