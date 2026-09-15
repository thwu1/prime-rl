cmake_minimum_required(VERSION 3.1.0...4.0.0)
project(RayTracer LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include_directories(src)

file(GLOB HEADERS "src/*.h")
add_executable(raytracer src/main.cc ${HEADERS})
