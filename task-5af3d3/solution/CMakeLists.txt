cmake_minimum_required(VERSION 3.18)
project(succinct_query_engine CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Disable SDSL extras when including as subdirectory
set(SDSL_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(SDSL_BUILD_TUTORIAL OFF CACHE BOOL "" FORCE)
set(SDSL_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)

add_subdirectory(/opt/sdsl-lite ${CMAKE_BINARY_DIR}/sdsl-lite-build)

add_executable(solve solve.cpp)
target_link_libraries(solve sdsl-lite::sdsl-lite)
target_compile_options(solve PRIVATE -O2)
