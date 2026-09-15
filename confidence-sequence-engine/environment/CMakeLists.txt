cmake_minimum_required(VERSION 3.14)
project(confseq_tests CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(test_runner test_runner.cpp)
target_include_directories(test_runner PRIVATE ${CMAKE_SOURCE_DIR})
