cmake_minimum_required(VERSION 3.16)
project(wgef-tools C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -O2 -Wall")

# Shared bitstream library
add_library(wgef_bits STATIC bitstream.c)
target_include_directories(wgef_bits PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

# Diagnostic tools
add_executable(header_info header_info.c)
target_link_libraries(header_info PRIVATE wgef_bits)

add_executable(bitprobe bitprobe.c)
target_link_libraries(bitprobe PRIVATE wgef_bits)

add_executable(ef_dump ef_dump.c)
target_link_libraries(ef_dump PRIVATE wgef_bits m)
