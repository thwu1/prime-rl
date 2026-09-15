cmake_minimum_required(VERSION 3.18)
project(analyzer CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(SDSL_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(SDSL_BUILD_TUTORIAL OFF CACHE BOOL "" FORCE)
set(SDSL_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)

add_subdirectory(/opt/sdsl-lite ${CMAKE_BINARY_DIR}/sdsl-build)

add_executable(analyzer analyzer.cpp)
target_link_libraries(analyzer sdsl-lite::sdsl-lite)
target_compile_options(analyzer PRIVATE -O2)
