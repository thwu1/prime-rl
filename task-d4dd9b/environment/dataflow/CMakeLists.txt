cmake_minimum_required(VERSION 3.16)
project(DataFlow VERSION 2.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)

add_library(dataflow STATIC
    src/core.cpp
    src/pipeline.cpp
    src/codec.cpp
)
target_include_directories(dataflow PUBLIC
    $<BUILD_INTERFACE:${CMAKE_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

install(TARGETS dataflow ARCHIVE DESTINATION lib)
install(DIRECTORY include/ DESTINATION include)
