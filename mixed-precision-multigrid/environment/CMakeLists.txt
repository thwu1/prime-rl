cmake_minimum_required(VERSION 3.16)
project(poisson_gen C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

find_library(MATH_LIBRARY m)

add_executable(poisson_gen
    src/main.c
    src/stencil.c
)

target_include_directories(poisson_gen PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

if(MATH_LIBRARY)
    target_link_libraries(poisson_gen ${MATH_LIBRARY})
endif()

install(TARGETS poisson_gen RUNTIME DESTINATION bin)
