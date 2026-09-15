
cmake_minimum_required(VERSION 3.10)
project(posit16_arith LANGUAGES C)

set(CMAKE_C_STANDARD 90)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_compile_options(-O2 -Wall -Wextra -Werror -pedantic)

set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Shared library
add_library(posit16 SHARED posit16.c)

# Test driver
add_executable(test_driver test_driver.c)
target_link_libraries(test_driver PRIVATE posit16)

set(CMAKE_SKIP_BUILD_RPATH TRUE)
