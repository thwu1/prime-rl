cmake_minimum_required(VERSION 3.10)
project(FloodRouting CXX)

set(CMAKE_CXX_STANDARD 17)

add_executable(flood_sim
    src/main.cpp
    src/geom.cpp
)
