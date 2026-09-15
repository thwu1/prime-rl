cmake_minimum_required(VERSION 3.10)
project(cpi_groundtruth CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Eigen3 REQUIRED)

include_directories(${CMAKE_SOURCE_DIR})

add_executable(generate_groundtruth
    generate_groundtruth.cpp
    cpi/CpiV1.cpp
)
