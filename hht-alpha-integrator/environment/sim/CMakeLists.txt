cmake_minimum_required(VERSION 3.16)
project(pendulum_sim CXX)

find_package(Eigen REQUIRED)

add_executable(sim
    src/main.cpp
    src/pendulum.cpp
    src/integrator.cpp
)
target_link_libraries(sim Eigen::eigen)
set_target_properties(sim PROPERTIES CXX_STANDARD 17)
