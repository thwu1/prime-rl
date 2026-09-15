cmake_minimum_required(VERSION 3.5)
project(evalImpl)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++17")
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../include)

set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../../lib)

add_library(eval_11_null_001 SHARED evalimpl.cpp)
