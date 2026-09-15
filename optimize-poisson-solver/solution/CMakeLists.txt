cmake_minimum_required(VERSION 3.14)
project(poisson3d_project LANGUAGES C)

find_package(OpenMP REQUIRED)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
add_compile_options(-O2 -Wall)

add_executable(poisson3d poisson3d.c)
target_link_libraries(poisson3d PRIVATE m)

add_executable(fast_poisson fast_poisson.c)
target_link_libraries(fast_poisson PRIVATE m OpenMP::OpenMP_C)
