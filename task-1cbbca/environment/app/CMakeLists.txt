cmake_minimum_required(VERSION 3.16)
project(bipartite_buf_test CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

find_package(Threads REQUIRED)

add_executable(test_bipartite tests/test_bipartite.cpp)
target_include_directories(test_bipartite PRIVATE include)
target_link_libraries(test_bipartite PRIVATE Threads::Threads)
