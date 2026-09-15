cmake_minimum_required(VERSION 3.16)
project(sgemm C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -O3 -mavx2 -mfma")

add_executable(test_runner
    src/naive.c
    src/optimized.c
    test_runner.c
)
target_include_directories(test_runner PRIVATE include)
target_link_libraries(test_runner m)
