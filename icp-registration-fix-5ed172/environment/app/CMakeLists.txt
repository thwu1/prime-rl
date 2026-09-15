cmake_minimum_required(VERSION 3.10)
project(registration_pipeline CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Eigen3 3.3 REQUIRED)

add_executable(register_clouds
    src/main.cpp
    src/registration.cpp
    src/point_cloud.cpp
)

target_include_directories(register_clouds PRIVATE src/)
target_link_libraries(register_clouds Eigen3::Eigen)
