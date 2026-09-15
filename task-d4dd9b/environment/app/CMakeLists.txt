cmake_minimum_required(VERSION 3.16)
project(sigframe VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_subdirectory(src/parser)
add_subdirectory(src/executor)

add_executable(sigframe src/main.cpp)
target_link_libraries(sigframe PRIVATE parser executor)
