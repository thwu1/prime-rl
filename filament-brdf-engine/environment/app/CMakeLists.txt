cmake_minimum_required(VERSION 3.16)
project(filament_brdf C)

set(CMAKE_C_STANDARD 11)

# Performance tuning options
option(BRDF_FAST_FRESNEL "Use fast Fresnel approximation for better performance" ON)

add_library(brdf SHARED src/brdf.c)
target_include_directories(brdf PUBLIC ${CMAKE_SOURCE_DIR}/src)

if(BRDF_FAST_FRESNEL)
    target_compile_definitions(brdf PRIVATE BRDF_FAST_FRESNEL)
endif()

target_compile_options(brdf PRIVATE -Wall -Wextra -O2)
target_link_libraries(brdf m)
