
cmake_minimum_required(VERSION 3.16)
project(smem_bank_lib C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Build the shared memory bank conflict analysis library.
add_library(smembank src/smem_bank.c)

target_include_directories(smembank PUBLIC
    $<BUILD_INTERFACE:${CMAKE_SOURCE_DIR}/src>
)

install(TARGETS smembank
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
)
