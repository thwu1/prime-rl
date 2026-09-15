cmake_minimum_required(VERSION 3.16)
project(ntsum CXX)

set(CMAKE_CXX_STANDARD 17)

add_executable(engine engine.cpp)
target_compile_options(engine PRIVATE -O2 -Wall -Wextra)
